import json
import time

import requests

import config


class DeepSeekError(Exception):
    def __init__(self, message, request_id=None):
        self.request_id = request_id
        suffix = f" (request_id: {request_id})" if request_id else ""
        super().__init__(f"{message}{suffix}")


def _headers():
    if not config.DEEPSEEK_API_KEY:
        raise DeepSeekError("DEEPSEEK_API_KEY is not configured")
    return {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }


def _extract_error(data, fallback):
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return fallback


def _retry_delay(attempt, response=None):
    retry_after = response.headers.get("Retry-After") if response is not None else None
    try:
        delay = float(retry_after) if retry_after else 0
    except (TypeError, ValueError):
        delay = 0
    if delay <= 0:
        delay = config.DEEPSEEK_RETRY_BASE_SECONDS * (2 ** attempt)
    return min(delay, config.DEEPSEEK_RETRY_MAX_SECONDS)


def _request_json(payload, operation):
    response = None
    for attempt in range(config.DEEPSEEK_MAX_ATTEMPTS):
        try:
            response = requests.post(
                config.DEEPSEEK_CHAT_URL,
                headers=_headers(),
                json=payload,
                timeout=(
                    config.DEEPSEEK_CONNECT_TIMEOUT_SECONDS,
                    config.DEEPSEEK_REQUEST_TIMEOUT_SECONDS,
                ),
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt + 1 >= config.DEEPSEEK_MAX_ATTEMPTS:
                message = (
                    f"DeepSeek {operation} timed out after retries"
                    if isinstance(exc, requests.Timeout)
                    else f"DeepSeek connection failed after retries: {exc}"
                )
                raise DeepSeekError(message) from exc
            time.sleep(_retry_delay(attempt))
            continue
        except requests.RequestException as exc:
            raise DeepSeekError(f"DeepSeek network error: {exc}") from exc

        request_id = response.headers.get("x-request-id")
        if response.status_code in {408, 429} or response.status_code >= 500:
            if attempt + 1 < config.DEEPSEEK_MAX_ATTEMPTS:
                time.sleep(_retry_delay(attempt, response))
                continue

        try:
            data = response.json()
        except ValueError as exc:
            if attempt + 1 < config.DEEPSEEK_MAX_ATTEMPTS:
                time.sleep(_retry_delay(attempt, response))
                continue
            raise DeepSeekError(
                f"DeepSeek returned a non-JSON response (HTTP {response.status_code})",
                request_id,
            ) from exc
        if not response.ok:
            message = _extract_error(data, f"HTTP {response.status_code}")
            raise DeepSeekError(f"DeepSeek API error: {message}", request_id)
        return data, request_id

    raise DeepSeekError(f"DeepSeek {operation} failed after retries")


def _parse_json_content(content, request_id):
    """Parse JSON from plain text, fenced output, reasoning text, or content blocks."""
    if isinstance(content, (dict, list)):
        if isinstance(content, list):
            block_text = [
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("text")
            ]
            if block_text:
                content = "\n".join(block_text)
            else:
                return content
        else:
            return content

    text = str(content or "").lstrip("\ufeff").strip()
    if not text:
        raise DeepSeekError("DeepSeek returned empty JSON content", request_id)

    # First handle responses that are already pure JSON, including JSON encoded as a string.
    candidate = text
    for _ in range(2):
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            break
        if isinstance(parsed, str):
            candidate = parsed.strip()
            continue
        return parsed

    # Models sometimes prepend reasoning or prose, or wrap the object in markdown. Scan
    # for the first complete JSON object/array instead of relying on exact fence placement.
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character not in "{[":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed

    raise DeepSeekError("DeepSeek returned invalid dialogue JSON", request_id)


def _extract_message_content(data, request_id):
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError("DeepSeek returned an unexpected response", request_id) from exc

    candidates = (
        message.get("content"),
        message.get("reasoning_content"),
        message.get("output_text"),
        choice.get("text"),
        data.get("output_text") if isinstance(data, dict) else None,
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
        if isinstance(candidate, (dict, list)) and candidate:
            return candidate
    return ""


def _build_repair_payload(payload, content, repair_prompt):
    if isinstance(content, str):
        previous_content = content.strip()
    elif content:
        previous_content = json.dumps(content, ensure_ascii=False)
    else:
        previous_content = ""

    messages = list(payload["messages"])
    if previous_content:
        messages.append({"role": "assistant", "content": previous_content[:12000]})
    messages.append({"role": "user", "content": repair_prompt})

    repaired = {**payload, "messages": messages}
    # Some DeepSeek models return an empty content field when JSON mode is enabled.
    # The parser already extracts JSON from ordinary text, so retry without JSON mode.
    repaired.pop("response_format", None)
    repaired["max_tokens"] = min(
        8192, max(2048, int(payload.get("max_tokens", 1024) * 2))
    )
    return repaired


def _find_turns_container(script):
    if isinstance(script, list):
        return script
    if not isinstance(script, dict):
        return None
    for key in ("turns", "dialogue", "conversation", "messages"):
        value = script.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _find_turns_container(value)
            if nested is not None:
                return nested
    return None


def _normalize_dialogue(script, roles, max_turns, request_id):
    raw_turns = _find_turns_container(script)
    if raw_turns is None:
        raise DeepSeekError("DeepSeek JSON does not contain a turns array", request_id)
    if not raw_turns:
        raise DeepSeekError("DeepSeek returned an empty dialogue", request_id)
    if len(raw_turns) > max_turns:
        raise DeepSeekError(
            f"DeepSeek returned {len(raw_turns)} turns; maximum is {max_turns}",
            request_id,
        )

    role_lookup = {role.casefold(): role for role in roles}
    turns = []
    for index, item in enumerate(raw_turns):
        if not isinstance(item, dict):
            raise DeepSeekError(f"Dialogue turn {index + 1} is not an object", request_id)
        speaker = str(
            item.get("speaker") or item.get("role") or item.get("character") or ""
        ).strip()
        text = str(
            item.get("text") or item.get("content") or item.get("utterance") or ""
        ).strip()
        speaker = role_lookup.get(speaker.casefold(), speaker)
        if speaker not in roles:
            raise DeepSeekError(
                f"Generated script contains an unknown role: {speaker or '<empty>'}",
                request_id,
            )
        if not text:
            raise DeepSeekError(f"Dialogue turn {index + 1} has empty text", request_id)
        turns.append({"speaker": speaker, "text": text, "timestamp": None})
    return turns


def _find_variants_container(value):
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return None
    for key in (
        "variants",
        "variations",
        "scenario_variants",
        "scenarios",
        "items",
        "results",
        "data",
        "output",
        "response",
    ):
        nested = value.get(key)
        if isinstance(nested, list):
            return nested
        if isinstance(nested, dict):
            found = _find_variants_container(nested)
            if found is not None:
                return found
            indexed_values = list(nested.values())
            if indexed_values and all(
                isinstance(item, (dict, str)) for item in indexed_values
            ):
                return indexed_values
    if any(key in value for key in ("title", "scenario", "trigger", "description")):
        return [value]
    return None


def _first_text(item, *keys):
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_variants(parsed, count, request_id):
    raw_variants = _find_variants_container(parsed)
    if raw_variants is None:
        raise DeepSeekError("DeepSeek JSON does not contain a variants array", request_id)
    if len(raw_variants) != count:
        raise DeepSeekError(
            f"DeepSeek returned {len(raw_variants)} variants; exactly {count} are required",
            request_id,
        )

    default_tones = [
        "calm and cautious",
        "urgent and concerned",
        "confused but cooperative",
        "frustrated but respectful",
        "detail-oriented and analytical",
        "anxious and reassurance-seeking",
        "direct and time-conscious",
        "patient and exploratory",
        "skeptical and security-conscious",
        "proactive and prevention-focused",
    ]
    normalized = []
    seen_titles = set()
    for index, variant in enumerate(raw_variants):
        if isinstance(variant, str):
            variant = {"title": variant, "trigger": variant}
        if not isinstance(variant, dict):
            raise DeepSeekError(f"Variant {index + 1} is not an object", request_id)

        title = _first_text(variant, "title", "name", "scenario", "summary")
        trigger = _first_text(
            variant, "trigger", "situation", "scenario", "description", "context"
        )
        customer_profile = _first_text(
            variant, "customer_profile", "profile", "customer", "persona"
        )
        tone = _first_text(variant, "tone", "emotion", "mood")
        goal = _first_text(
            variant, "goal", "resolution", "outcome", "objective", "expected_result"
        )

        title = title or f"Variation {index + 1}"
        trigger = trigger or title
        customer_profile = customer_profile or f"Customer context for variation {index + 1}"
        tone = tone or default_tones[index % len(default_tones)]
        goal = goal or f"Resolve the request through path {index + 1}"

        title_key = title.casefold()
        if title_key in seen_titles:
            title = f"{title} - Variation {index + 1}"
            title_key = title.casefold()
        seen_titles.add(title_key)
        normalized.append(
            {
                "title": title,
                "customer_profile": customer_profile,
                "trigger": trigger,
                "tone": tone,
                "goal": goal,
            }
        )
    return normalized


def _fallback_variants(count):
    plans = [
        ("First-time inquiry", "A first-time customer needs step-by-step guidance", "The customer has just discovered the issue", "calm and cautious", "Explain the standard resolution clearly"),
        ("Urgent request", "A time-conscious customer needs immediate help", "The issue is actively affecting the customer", "urgent and concerned", "Prioritize immediate protective actions"),
        ("Follow-up contact", "A customer is following up after an earlier attempt", "The previous contact did not fully resolve the matter", "frustrated but respectful", "Review prior steps and complete the resolution"),
        ("Limited technical experience", "A customer needs simple, accessible instructions", "The customer cannot easily use digital self-service", "confused but cooperative", "Offer an easy assisted path"),
        ("Detailed options review", "A detail-oriented customer wants to compare choices", "The customer asks about requirements and consequences", "analytical and careful", "Compare options before confirming next steps"),
        ("Security-focused concern", "A cautious customer is worried about account safety", "Unexpected activity has increased the customer's concern", "anxious and security-conscious", "Verify identity and provide reassurance"),
        ("Travel constraint", "A customer is away from their usual location", "The customer has limited access to normal channels", "direct and time-conscious", "Find a resolution that works remotely"),
        ("Representative inquiry", "A customer asks what can be done for another account holder", "Authority and identity requirements are unclear", "patient and exploratory", "Clarify authorization and available assistance"),
        ("Repeated problem", "A customer reports that the same issue has happened again", "Earlier preventive steps were not sufficient", "skeptical and frustrated", "Escalate appropriately and prevent recurrence"),
        ("Proactive planning", "A customer wants to prepare before a problem occurs", "The customer is reviewing preventive options", "proactive and calm", "Explain prevention and future support channels"),
    ]
    return [
        {
            "title": plans[index][0],
            "customer_profile": plans[index][1],
            "trigger": plans[index][2],
            "tone": plans[index][3],
            "goal": plans[index][4],
        }
        for index in range(count)
    ]


def generate_scenario_variants(scenario, count, language="en"):
    """Create distinct planning briefs for multiple dialogues about one base topic."""
    language_config = config.SUPPORTED_LANGUAGES.get(language)
    if language_config is None:
        raise DeepSeekError(f"Unsupported output language: {language}")
    if not 1 <= count <= config.MAX_BATCH_AUDIO_COUNT:
        raise DeepSeekError(
            f"Variant count must be between 1 and {config.MAX_BATCH_AUDIO_COUNT}"
        )

    system_prompt = (
        "You plan diverse customer-service simulation dialogues. Respond with one valid "
        "JSON object and no markdown. The JSON shape is "
        '{"variants":[{"title":"...","customer_profile":"...",'
        '"trigger":"...","tone":"...","goal":"..."}]}. '
        f"Return exactly {count} variants. Every variant must stay on the same base topic, "
        "but use a meaningfully different customer context, trigger, emotional tone, "
        "question path, or resolution path. Do not create superficial variants that only "
        f"change names or numbers. Write the planning fields in {language_config['prompt']}."
    )
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": scenario},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": min(4096, max(1024, count * 220)),
        "stream": False,
    }
    max_attempts = config.DEEPSEEK_CONTENT_MAX_ATTEMPTS
    for attempt in range(max_attempts):
        data, request_id = _request_json(payload, "scenario planning")
        content = _extract_message_content(data, request_id)
        try:
            parsed = _parse_json_content(content, request_id)
            return _normalize_variants(parsed, count, request_id)
        except DeepSeekError:
            if attempt + 1 >= max_attempts:
                # Script generation still uses DeepSeek. These deterministic planning angles
                # keep the batch usable if the model repeatedly ignores the planning schema.
                return _fallback_variants(count)
            repair_prompt = (
                "Your previous response did not contain the required scenario variants. "
                f"Return exactly {count} items in one JSON object under the key "
                '"variants". Every item must contain non-empty title, customer_profile, '
                'trigger, tone, and goal fields. Return JSON only, with no markdown, '
                "reasoning, comments, or text outside the JSON object."
            )
            payload = _build_repair_payload(payload, content, repair_prompt)
            time.sleep(_retry_delay(attempt))

    return _fallback_variants(count)


def generate_dialogue_script(scenario, roles, max_turns=20, language="en"):
    """Generate one structured dialogue script using DeepSeek JSON Output."""
    language_config = config.SUPPORTED_LANGUAGES.get(language)
    if language_config is None:
        raise DeepSeekError(f"Unsupported output language: {language}")

    role_list = ", ".join(roles)
    system_prompt = (
        "You generate realistic spoken dialogue scripts for customer-service simulations. "
        "You must respond with one valid JSON object and no markdown. The JSON shape is "
        '{"turns":[{"speaker":"<allowed role>","text":"<spoken line>"}]}. '
        f"The only allowed speaker values are: {role_list}. "
        f"Generate no more than {max_turns} turns. Write every spoken line exclusively in "
        f"{language_config['prompt']}, regardless of the language used in the scenario. "
        "Keep every role's identity, speaking style, and knowledge consistent across all turns."
    )
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": scenario},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": min(8192, max(1024, max_turns * 160)),
        "stream": False,
    }

    max_attempts = config.DEEPSEEK_CONTENT_MAX_ATTEMPTS
    for attempt in range(max_attempts):
        data, request_id = _request_json(payload, "script generation")
        content = _extract_message_content(data, request_id)
        try:
            script = _parse_json_content(content, request_id)
            turns = _normalize_dialogue(script, roles, max_turns, request_id)
        except DeepSeekError:
            if attempt + 1 >= max_attempts:
                raise
            repair_prompt = (
                "Your previous response could not be parsed as the required dialogue. "
                "Return only one valid JSON object with exactly this shape: "
                '{"turns":[{"speaker":"<allowed role>","text":"<spoken line>"}]}. '
                f"Allowed speaker values: {role_list}. Do not include markdown, reasoning, "
                "comments, or any text outside the JSON object."
            )
            payload = _build_repair_payload(payload, content, repair_prompt)
            time.sleep(_retry_delay(attempt))
            continue

        return {
            "turns": turns,
            "request_id": request_id or data.get("id"),
            "model": data.get("model", config.DEEPSEEK_MODEL),
            "usage": data.get("usage", {}),
        }

    raise DeepSeekError("DeepSeek dialogue generation failed after format repair")
