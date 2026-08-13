import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import chatlog_parser
import config
import minimax_client
import deepseek_client
from audio_assembler import AudioAssemblyError, assemble_dialogue
from batch_jobs import BatchJobError, batch_job_manager

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_BYTES
CORS(app, resources={r"/api/*": {"origins": config.CORS_ORIGINS}})

os.makedirs(config.UPLOAD_DIR, exist_ok=True)
os.makedirs(config.OUTPUT_DIR, exist_ok=True)


@app.errorhandler(413)
def upload_too_large(_error):
    max_mb = config.MAX_UPLOAD_BYTES / (1024 * 1024)
    return jsonify({"error": f"Uploaded file exceeds the {max_mb:g} MB limit"}), 413


def _json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, (jsonify({"error": "Request body must be a JSON object"}), 400)
    return body, None


def _validate_roles(raw_roles):
    if not isinstance(raw_roles, list):
        raise ValueError("Roles must be a JSON array")
    roles = []
    for value in raw_roles:
        role = str(value).strip()
        if not role:
            raise ValueError("Role names cannot be empty")
        if len(role) > 50:
            raise ValueError("Role names cannot exceed 50 characters")
        if role not in roles:
            roles.append(role)
    if not roles:
        raise ValueError("At least one role is required")
    if len(roles) > config.MAX_ROLES:
        raise ValueError(f"A maximum of {config.MAX_ROLES} roles is supported")
    return roles


def _validate_language(value, allow_auto=False):
    language = str(value or "").strip()
    if allow_auto and language == "auto":
        return language
    if language not in config.SUPPORTED_LANGUAGES:
        allowed = ", ".join(config.SUPPORTED_LANGUAGES)
        raise ValueError(f"language must be one of: {allowed}")
    return language


def _validate_scenario(value, label="Scenario"):
    scenario = str(value or "").strip()
    if not scenario:
        raise ValueError(f"{label} is required")
    if len(scenario) > config.MAX_SCENARIO_CHARS:
        raise ValueError(
            f"{label} cannot exceed {config.MAX_SCENARIO_CHARS} characters"
        )
    return scenario


def _validate_max_turns(value):
    if isinstance(value, bool):
        raise ValueError("max_turns must be an integer")
    try:
        max_turns = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_turns must be an integer") from exc
    if not 1 <= max_turns <= config.MAX_DIALOGUE_TURNS:
        raise ValueError(
            f"max_turns must be between 1 and {config.MAX_DIALOGUE_TURNS}"
        )
    return max_turns


def _validate_batch_count(value):
    if isinstance(value, bool):
        raise ValueError("count must be an integer")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("count must be an integer") from exc
    if not 1 <= count <= config.MAX_BATCH_AUDIO_COUNT:
        raise ValueError(
            f"count must be between 1 and {config.MAX_BATCH_AUDIO_COUNT}"
        )
    return count


def _validate_gap_ms(value):
    if isinstance(value, bool):
        raise ValueError("gap_ms must be an integer")
    try:
        gap_ms = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("gap_ms must be an integer") from exc
    if not 0 <= gap_ms <= config.MAX_GAP_MS:
        raise ValueError(f"gap_ms must be between 0 and {config.MAX_GAP_MS}")
    return gap_ms


def _validate_role_voice_map(raw_mapping, roles, language):
    if not isinstance(raw_mapping, dict):
        raise ValueError("role_voice_map must be a JSON object")
    mapping = {
        role: str(raw_mapping.get(role, "")).strip()
        for role in roles
    }
    missing_roles = [role for role, voice_id in mapping.items() if not voice_id]
    if missing_roles:
        raise ValueError(f"No voice assigned for role(s): {sorted(missing_roles)}")

    voices_by_id = {voice["voice_id"]: voice for voice in config.PRESET_VOICES}
    unknown_ids = sorted({voice_id for voice_id in mapping.values() if voice_id not in voices_by_id})
    if unknown_ids:
        raise ValueError(f"Unknown voice_id(s): {unknown_ids}")

    expected_language = config.SUPPORTED_LANGUAGES[language]["voice_language"]
    mismatched = sorted(
        {
            voice_id
            for voice_id in mapping.values()
            if voices_by_id[voice_id].get("language")
            and voices_by_id[voice_id]["language"] != expected_language
        }
    )
    if mismatched:
        raise ValueError(
            f"Voice ID(s) do not match the selected language: {mismatched}"
        )
    return mapping


def _validate_turns(raw_turns):
    if not isinstance(raw_turns, list) or not raw_turns:
        raise ValueError("Dialogue content is empty or invalid")
    if len(raw_turns) > config.MAX_DIALOGUE_TURNS:
        raise ValueError(
            f"A maximum of {config.MAX_DIALOGUE_TURNS} dialogue turns is supported"
        )

    turns = []
    total_chars = 0
    for index, turn in enumerate(raw_turns):
        if not isinstance(turn, dict):
            raise ValueError(f"Dialogue turn {index + 1} must be an object")
        speaker = str(turn.get("speaker", "")).strip()
        text = str(turn.get("text", "")).strip()
        if not speaker:
            raise ValueError(f"Dialogue turn {index + 1} has no speaker")
        if len(speaker) > 50:
            raise ValueError(f"Dialogue turn {index + 1} speaker is too long")
        if not text:
            raise ValueError(f"Dialogue turn {index + 1} has empty text")
        if len(text) > config.MAX_TURN_TEXT_CHARS:
            raise ValueError(
                f"Dialogue turn {index + 1} exceeds {config.MAX_TURN_TEXT_CHARS} characters"
            )
        total_chars += len(text)
        turns.append(
            {
                "speaker": speaker,
                "text": text,
                "timestamp": turn.get("timestamp") or None,
            }
        )

    if total_chars > config.MAX_TOTAL_TEXT_CHARS:
        raise ValueError(
            f"Dialogue exceeds the {config.MAX_TOTAL_TEXT_CHARS}-character total limit"
        )
    return turns


def _generate_batch_item(index, scenario, roles, max_turns, language):
    try:
        generated = deepseek_client.generate_dialogue_script(
            scenario, roles, max_turns=max_turns, language=language
        )
        turns = _validate_turns(generated["turns"])
        return {
            "index": index,
            "scenario": scenario,
            "status": "success",
            "turns": chatlog_parser.turns_to_json(turns),
            "turn_count": len(turns),
            "request_id": generated.get("request_id"),
            "model": generated.get("model", config.DEEPSEEK_MODEL),
            "language": language,
            "usage": generated.get("usage", {}),
        }
    except (deepseek_client.DeepSeekError, ValueError) as exc:
        return {
            "index": index,
            "scenario": scenario,
            "status": "error",
            "error": str(exc),
            "request_id": getattr(exc, "request_id", None),
        }


@app.post("/api/parse-chatlog")
def parse_chatlog():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file was uploaded"}), 400

    filename = file.filename
    extension = os.path.splitext(filename)[1].lower()
    if extension not in {".csv", ".txt"}:
        return jsonify({"error": "Only .csv and .txt chatlog files are supported"}), 400

    file_bytes = file.read()
    if not file_bytes:
        return jsonify({"error": "The uploaded file is empty"}), 400

    try:
        if extension == ".csv":
            turns = chatlog_parser.parse_csv(file_bytes)
        else:
            turns = chatlog_parser.parse_plain_text(file_bytes.decode("utf-8-sig"))
        turns = _validate_turns(turns)
    except (ValueError, UnicodeError) as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "roles": chatlog_parser.get_roles(turns),
            "turns": chatlog_parser.turns_to_json(turns),
        }
    )


@app.post("/api/generate-script")
def generate_script():
    body, error = _json_body()
    if error:
        return error

    try:
        scenario = _validate_scenario(body.get("scenario"))
        roles = _validate_roles(body.get("roles", []))
        max_turns = _validate_max_turns(body.get("max_turns", 20))
        language = _validate_language(body.get("language", "en"))
        generated = deepseek_client.generate_dialogue_script(
            scenario, roles, max_turns=max_turns, language=language
        )
        turns = _validate_turns(generated["turns"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except deepseek_client.DeepSeekError as exc:
        return jsonify({"error": str(exc), "request_id": exc.request_id}), 502

    return jsonify(
        {
            "roles": roles,
            "turns": chatlog_parser.turns_to_json(turns),
            "language": language,
            "request_id": generated.get("request_id"),
            "model": generated.get("model", config.DEEPSEEK_MODEL),
            "usage": generated.get("usage", {}),
        }
    )


@app.post("/api/generate-scripts-batch")
def generate_scripts_batch():
    body, error = _json_body()
    if error:
        return error

    try:
        roles = _validate_roles(body.get("roles", []))
        max_turns = _validate_max_turns(body.get("max_turns", 20))
        language = _validate_language(body.get("language", "en"))
        raw_scenarios = body.get("scenarios", [])
        if not isinstance(raw_scenarios, list):
            raise ValueError("scenarios must be a JSON array")
        if not raw_scenarios:
            raise ValueError("At least one scenario is required")
        if len(raw_scenarios) > config.MAX_BATCH_SCENARIOS:
            raise ValueError(
                f"A maximum of {config.MAX_BATCH_SCENARIOS} scenarios is supported per batch"
            )
        scenarios = [
            _validate_scenario(value, f"Scenario {index + 1}")
            for index, value in enumerate(raw_scenarios)
        ]
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    results = [None] * len(scenarios)
    max_workers = max(1, min(config.DEEPSEEK_BATCH_CONCURRENCY, len(scenarios)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _generate_batch_item, index, scenario, roles, max_turns, language
            ): index
            for index, scenario in enumerate(scenarios)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                results[index] = {
                    "index": index,
                    "scenario": scenarios[index],
                    "status": "error",
                    "error": f"Unexpected batch error: {exc}",
                    "request_id": None,
                }

    success_count = sum(item["status"] == "success" for item in results)
    return jsonify(
        {
            "roles": roles,
            "model": config.DEEPSEEK_MODEL,
            "language": language,
            "results": results,
            "success_count": success_count,
            "failure_count": len(results) - success_count,
            "total_count": len(results),
        }
    )


@app.post("/api/batch-jobs")
def create_batch_job():
    body, error = _json_body()
    if error:
        return error
    try:
        scenario = _validate_scenario(body.get("scenario"), "Base scenario")
        count = _validate_batch_count(body.get("count", 5))
        roles = _validate_roles(body.get("roles", []))
        language = _validate_language(body.get("language", "en"))
        max_turns = _validate_max_turns(body.get("max_turns", 12))
        gap_ms = _validate_gap_ms(body.get("gap_ms", config.DEFAULT_GAP_MS))
        role_voice_map = _validate_role_voice_map(
            body.get("role_voice_map", {}), roles, language
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    job = batch_job_manager.create_job(
        {
            "scenario": scenario,
            "count": count,
            "roles": roles,
            "language": language,
            "max_turns": max_turns,
            "gap_ms": gap_ms,
            "role_voice_map": role_voice_map,
        }
    )
    return jsonify(job), 202


@app.get("/api/batch-jobs/<job_id>")
def get_batch_job(job_id):
    job = batch_job_manager.get_job(job_id)
    if job is None:
        return jsonify({"error": "Batch job not found"}), 404
    return jsonify(job)


@app.post("/api/batch-jobs/<job_id>/retry")
def retry_batch_job(job_id):
    try:
        job = batch_job_manager.retry_failed(job_id)
    except BatchJobError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(job), 202


@app.get("/api/voices")
def list_voices():
    return jsonify({"voices": config.PRESET_VOICES})


@app.post("/api/generate-audio")
def generate_audio():
    body, error = _json_body()
    if error:
        return error

    try:
        turns = _validate_turns(body.get("turns", []))
        language = _validate_language(body.get("language", "auto"), allow_auto=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    role_voice_map = body.get("role_voice_map", {})
    if not isinstance(role_voice_map, dict):
        return jsonify({"error": "role_voice_map must be a JSON object"}), 400

    roles = chatlog_parser.get_roles(turns)
    missing_roles = [role for role in roles if not role_voice_map.get(role)]
    if missing_roles:
        return jsonify(
            {"error": f"No voice assigned for role(s): {sorted(missing_roles)}"}
        ), 400

    available_voice_ids = {voice["voice_id"] for voice in config.PRESET_VOICES}
    unknown_voice_ids = sorted(
        {
            str(role_voice_map[role]).strip()
            for role in roles
            if str(role_voice_map[role]).strip() not in available_voice_ids
        }
    )
    if unknown_voice_ids:
        return jsonify({"error": f"Unknown voice_id(s): {unknown_voice_ids}"}), 400

    raw_gap_ms = body.get("gap_ms", config.DEFAULT_GAP_MS)
    if isinstance(raw_gap_ms, bool):
        return jsonify({"error": "gap_ms must be an integer"}), 400
    try:
        gap_ms = int(raw_gap_ms)
    except (TypeError, ValueError):
        return jsonify({"error": "gap_ms must be an integer"}), 400
    if not 0 <= gap_ms <= config.MAX_GAP_MS:
        return jsonify(
            {"error": f"gap_ms must be between 0 and {config.MAX_GAP_MS}"}
        ), 400

    tts_language = (
        "auto"
        if language == "auto"
        else config.SUPPORTED_LANGUAGES[language]["minimax"]
    )
    try:
        synthesis_results = [
            minimax_client.synthesize_speech(
                turn["text"],
                str(role_voice_map[turn["speaker"]]).strip(),
                language_boost=tts_language,
            )
            for turn in turns
        ]
    except minimax_client.MiniMaxError as exc:
        return jsonify({"error": str(exc), "trace_id": exc.trace_id}), 502

    gaps_ms = [gap_ms] * max(0, len(turns) - 1)
    output_filename = f"dialogue_{uuid.uuid4().hex}.mp3"
    output_path = os.path.join(config.OUTPUT_DIR, output_filename)

    try:
        assemble_dialogue(
            [result["audio"] for result in synthesis_results], gaps_ms, output_path
        )
    except AudioAssemblyError as exc:
        if os.path.exists(output_path):
            os.remove(output_path)
        return jsonify({"error": str(exc)}), 500

    return jsonify(
        {
            "audio_url": f"/api/download/{output_filename}",
            "turn_count": len(turns),
            "gap_ms": gap_ms,
            "language": language,
            "trace_ids": [
                result["trace_id"]
                for result in synthesis_results
                if result.get("trace_id")
            ],
        }
    )


@app.get("/api/download/<path:filename>")
def download_file(filename):
    return send_from_directory(config.OUTPUT_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=config.DEBUG)
