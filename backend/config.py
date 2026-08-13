import json
import os

from dotenv import load_dotenv

load_dotenv()


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


# MiniMax international TTS
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "").strip()
MINIMAX_API_BASE = os.getenv("MINIMAX_API_BASE", "https://api.minimax.io").rstrip("/")
MINIMAX_T2A_URL = os.getenv("MINIMAX_T2A_URL", f"{MINIMAX_API_BASE}/v1/t2a_v2")
TTS_MODEL = os.getenv("MINIMAX_TTS_MODEL", "speech-2.8-turbo")
MINIMAX_CONNECT_TIMEOUT_SECONDS = _env_int("MINIMAX_CONNECT_TIMEOUT_SECONDS", 10)
MINIMAX_REQUEST_TIMEOUT_SECONDS = _env_int("MINIMAX_REQUEST_TIMEOUT_SECONDS", 180)
MINIMAX_MAX_ATTEMPTS = max(1, _env_int("MINIMAX_MAX_ATTEMPTS", 3))
MINIMAX_RETRY_BASE_SECONDS = max(0, _env_float("MINIMAX_RETRY_BASE_SECONDS", 1))
MINIMAX_RETRY_MAX_SECONDS = max(0, _env_float("MINIMAX_RETRY_MAX_SECONDS", 8))

# DeepSeek script generation
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_CHAT_URL = os.getenv(
    "DEEPSEEK_CHAT_URL", f"{DEEPSEEK_API_BASE}/chat/completions"
)
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_CONNECT_TIMEOUT_SECONDS = _env_int("DEEPSEEK_CONNECT_TIMEOUT_SECONDS", 10)
DEEPSEEK_REQUEST_TIMEOUT_SECONDS = _env_int("DEEPSEEK_REQUEST_TIMEOUT_SECONDS", 120)
DEEPSEEK_MAX_ATTEMPTS = max(1, _env_int("DEEPSEEK_MAX_ATTEMPTS", 3))
DEEPSEEK_RETRY_BASE_SECONDS = max(0, _env_float("DEEPSEEK_RETRY_BASE_SECONDS", 1))
DEEPSEEK_RETRY_MAX_SECONDS = max(0, _env_float("DEEPSEEK_RETRY_MAX_SECONDS", 8))
DEEPSEEK_CONTENT_MAX_ATTEMPTS = max(2, _env_int("DEEPSEEK_CONTENT_MAX_ATTEMPTS", 3))
DEEPSEEK_BATCH_CONCURRENCY = _env_int("DEEPSEEK_BATCH_CONCURRENCY", 2)

SUPPORTED_LANGUAGES = {
    "en": {
        "label": "English",
        "prompt": "English",
        "minimax": "English",
        "voice_language": "English",
    },
    "zh-CN": {
        "label": "普通话",
        "prompt": "Simplified Chinese in standard Mandarin",
        "minimax": "Chinese",
        "voice_language": "Chinese",
    },
    "yue": {
        "label": "粤语",
        "prompt": "natural spoken Cantonese written in Traditional Chinese",
        "minimax": "Chinese,Yue",
        "voice_language": "Yue",
    },
}

AUDIO_SETTING = {
    "sample_rate": _env_int("MINIMAX_SAMPLE_RATE", 32000),
    "bitrate": _env_int("MINIMAX_BITRATE", 128000),
    "format": os.getenv("MINIMAX_AUDIO_FORMAT", "mp3"),
    "channel": _env_int("MINIMAX_AUDIO_CHANNELS", 1),
}

_DEFAULT_VOICES = [
    {
        "voice_id": "English_expressive_narrator",
        "name": "English Expressive Narrator",
        "language": "English",
    },
    {
        "voice_id": "English_radiant_girl",
        "name": "English Radiant Girl",
        "language": "English",
    },
    {
        "voice_id": "Chinese (Mandarin)_Reliable_Executive",
        "name": "Mandarin Reliable Executive",
        "language": "Chinese",
    },
    {
        "voice_id": "Chinese (Mandarin)_News_Anchor",
        "name": "Mandarin News Anchor",
        "language": "Chinese",
    },
    {
        "voice_id": "Cantonese_Articulate_commentator_vv2",
        "name": "Cantonese Customer Service",
        "language": "Yue",
    },
    {
        "voice_id": "Cantonese_casual_narrator_vv2",
        "name": "Cantonese Customer",
        "language": "Yue",
    },
]


def _load_preset_voices():
    raw = os.getenv("MINIMAX_VOICES_JSON", "").strip()
    if not raw:
        return _DEFAULT_VOICES

    try:
        voices = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("MINIMAX_VOICES_JSON must be valid JSON") from exc

    if not isinstance(voices, list) or not voices:
        raise RuntimeError("MINIMAX_VOICES_JSON must be a non-empty JSON array")

    normalized = []
    seen_ids = set()
    for index, voice in enumerate(voices):
        if not isinstance(voice, dict):
            raise RuntimeError(f"MINIMAX_VOICES_JSON item {index + 1} must be an object")
        voice_id = str(voice.get("voice_id", "")).strip()
        name = str(voice.get("name", "")).strip()
        if not voice_id or not name:
            raise RuntimeError(
                f"MINIMAX_VOICES_JSON item {index + 1} requires voice_id and name"
            )
        if voice_id in seen_ids:
            raise RuntimeError(f"Duplicate voice_id in MINIMAX_VOICES_JSON: {voice_id}")
        seen_ids.add(voice_id)
        normalized_voice = {"voice_id": voice_id, "name": name}
        if voice.get("language"):
            normalized_voice["language"] = str(voice["language"]).strip()
        normalized.append(normalized_voice)
    merged = {voice["voice_id"]: dict(voice) for voice in _DEFAULT_VOICES}
    for voice in normalized:
        merged[voice["voice_id"]] = voice
    return list(merged.values())


PRESET_VOICES = _load_preset_voices()

# API and upload limits
MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_BYTES", 5 * 1024 * 1024)
MAX_DIALOGUE_TURNS = _env_int("MAX_DIALOGUE_TURNS", 100)
MAX_TURN_TEXT_CHARS = _env_int("MAX_TURN_TEXT_CHARS", 3000)
MAX_TOTAL_TEXT_CHARS = _env_int("MAX_TOTAL_TEXT_CHARS", 30000)
MAX_ROLES = _env_int("MAX_ROLES", 10)
MAX_SCENARIO_CHARS = _env_int("MAX_SCENARIO_CHARS", 10000)
MAX_BATCH_SCENARIOS = _env_int("MAX_BATCH_SCENARIOS", 10)
MAX_BATCH_AUDIO_COUNT = _env_int("MAX_BATCH_AUDIO_COUNT", 10)
BATCH_JOB_CONCURRENCY = _env_int("BATCH_JOB_CONCURRENCY", 1)
MINIMAX_BATCH_CONCURRENCY = _env_int("MINIMAX_BATCH_CONCURRENCY", 1)
BATCH_SIMILARITY_THRESHOLD = _env_float("BATCH_SIMILARITY_THRESHOLD", 0.8)
DEFAULT_GAP_MS = _env_int("DEFAULT_GAP_MS", 250)
MAX_GAP_MS = _env_int("MAX_GAP_MS", 3000)

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
DATA_DIR = os.path.join(BASE_DIR, "data")
BATCH_DATABASE_PATH = os.path.join(DATA_DIR, "batch_jobs.sqlite3")

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
DEBUG = _env_bool("FLASK_DEBUG", False)
