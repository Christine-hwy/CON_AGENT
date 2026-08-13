import time

import requests

import config


class MiniMaxError(Exception):
    def __init__(self, message, trace_id=None):
        self.trace_id = trace_id
        suffix = f" (trace_id: {trace_id})" if trace_id else ""
        super().__init__(f"{message}{suffix}")


_SESSION = requests.Session()


def _headers():
    if not config.MINIMAX_API_KEY:
        raise MiniMaxError("MINIMAX_API_KEY is not configured")
    return {
        "Authorization": f"Bearer {config.MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }


def _error_message(data, fallback):
    if not isinstance(data, dict):
        return fallback
    error = data.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    base_resp = data.get("base_resp")
    if isinstance(base_resp, dict) and base_resp.get("status_msg"):
        return str(base_resp["status_msg"])
    return fallback


def _retry_delay(attempt, response=None):
    retry_after = response.headers.get("Retry-After") if response is not None else None
    try:
        delay = float(retry_after) if retry_after else 0
    except (TypeError, ValueError):
        delay = 0
    if delay <= 0:
        delay = config.MINIMAX_RETRY_BASE_SECONDS * (2 ** attempt)
    return min(delay, config.MINIMAX_RETRY_MAX_SECONDS)


def _post_json(url, payload):
    response = None
    for attempt in range(config.MINIMAX_MAX_ATTEMPTS):
        try:
            response = _SESSION.post(
                url,
                headers=_headers(),
                json=payload,
                timeout=(
                    config.MINIMAX_CONNECT_TIMEOUT_SECONDS,
                    config.MINIMAX_REQUEST_TIMEOUT_SECONDS,
                ),
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt + 1 >= config.MINIMAX_MAX_ATTEMPTS:
                message = (
                    "MiniMax TTS request timed out after retries"
                    if isinstance(exc, requests.Timeout)
                    else f"MiniMax TTS connection failed after retries: {exc}"
                )
                raise MiniMaxError(message) from exc
            time.sleep(_retry_delay(attempt))
            continue
        except requests.RequestException as exc:
            raise MiniMaxError(f"MiniMax TTS network error: {exc}") from exc

        if response.status_code in {408, 429} or response.status_code >= 500:
            if attempt + 1 < config.MINIMAX_MAX_ATTEMPTS:
                time.sleep(_retry_delay(attempt, response))
                continue

        try:
            data = response.json()
        except ValueError as exc:
            if attempt + 1 < config.MINIMAX_MAX_ATTEMPTS:
                time.sleep(_retry_delay(attempt, response))
                continue
            raise MiniMaxError(
                f"MiniMax TTS returned a non-JSON response (HTTP {response.status_code})"
            ) from exc

        trace_id = data.get("trace_id") if isinstance(data, dict) else None
        if not response.ok:
            message = _error_message(data, f"HTTP {response.status_code}")
            raise MiniMaxError(f"MiniMax TTS error: {message}", trace_id)

        base_resp = data.get("base_resp", {}) if isinstance(data, dict) else {}
        if base_resp and base_resp.get("status_code", 0) != 0:
            message = _error_message(data, "unknown API error")
            raise MiniMaxError(f"MiniMax TTS error: {message}", trace_id)

        return data, trace_id

    raise MiniMaxError("MiniMax TTS request failed after retries")


def synthesize_speech(
    text, voice_id, speed=1, vol=1, pitch=0, language_boost="auto"
):
    if language_boost not in {"auto", "English", "Chinese", "Chinese,Yue"}:
        raise MiniMaxError(f"Unsupported TTS language: {language_boost}")

    payload = {
        "model": config.TTS_MODEL,
        "text": text,
        "stream": False,
        "output_format": "hex",
        "language_boost": language_boost,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed,
            "vol": vol,
            "pitch": pitch,
        },
        "audio_setting": config.AUDIO_SETTING,
        "subtitle_enable": False,
    }
    data, trace_id = _post_json(config.MINIMAX_T2A_URL, payload)

    audio_hex = data.get("data", {}).get("audio")
    if not audio_hex:
        raise MiniMaxError("MiniMax TTS returned no audio data", trace_id)
    try:
        audio = bytes.fromhex(audio_hex)
    except (TypeError, ValueError) as exc:
        raise MiniMaxError("MiniMax TTS returned invalid hex audio data", trace_id) from exc

    return {
        "audio": audio,
        "trace_id": trace_id,
        "extra_info": data.get("extra_info", {}),
    }
