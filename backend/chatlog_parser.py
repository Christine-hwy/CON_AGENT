import io
import math
import re
from datetime import datetime

import pandas as pd

COLUMN_ALIASES = {
    "speaker": ["speaker", "role", "角色", "说话人"],
    "text": ["text", "message", "content", "内容"],
    "timestamp": ["chat time", "timestamp", "time", "时间"],
}


def _find_column(columns, aliases):
    lowered = {c.lower().strip(): c for c in columns}
    for alias in aliases:
        if alias in lowered:
            return lowered[alias]
    return None


def _parse_timestamp(value):
    if value is None or value == "":
        return None
    if isinstance(value, float) and math.isnan(value):
        return None

    timestamp = str(value).strip()
    if not timestamp:
        return None

    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        pass

    for date_format in (
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%H:%M:%S",
        "%H:%M",
    ):
        try:
            return datetime.strptime(timestamp, date_format)
        except ValueError:
            continue
    return None


def parse_csv(file_bytes):
    df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8-sig")
    speaker_col = _find_column(df.columns, COLUMN_ALIASES["speaker"])
    text_col = _find_column(df.columns, COLUMN_ALIASES["text"])
    ts_col = _find_column(df.columns, COLUMN_ALIASES["timestamp"])

    if speaker_col is None or text_col is None:
        raise ValueError("Couldn't find a role or text column in the CSV — make sure it has Speaker/Text-style columns")

    turns = []
    for row_number, (_, row) in enumerate(df.iterrows(), start=2):
        text = str(row[text_col]).strip()
        if not text or text.lower() == "nan":
            continue
        speaker = str(row[speaker_col]).strip()
        if not speaker or speaker.lower() == "nan":
            raise ValueError(f"Missing speaker on CSV row {row_number}")
        turns.append({
            "speaker": speaker,
            "text": text,
            "timestamp": _parse_timestamp(row[ts_col]) if ts_col else None,
        })
    if not turns:
        raise ValueError("The CSV contains no dialogue rows")
    return turns


LINE_PATTERN = re.compile(
    r"^\s*(?:\[(?P<timestamp>[^\]]+)\]\s*)?"
    r"(?P<speaker>[^:：]{1,50})\s*[:：]\s*(?P<text>.+)$"
)


def parse_plain_text(text):
    turns = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = LINE_PATTERN.match(line)
        if not match:
            continue
        turns.append({
            "speaker": match.group("speaker").strip(),
            "text": match.group("text").strip(),
            "timestamp": _parse_timestamp(match.group("timestamp")),
        })
    if not turns:
        raise ValueError('Could not parse any dialogue — make sure each line is formatted as "Role: line"')
    return turns


def get_roles(turns):
    roles = []
    for turn in turns:
        if turn["speaker"] not in roles:
            roles.append(turn["speaker"])
    return roles


def turns_to_json(turns):
    result = []
    for turn in turns:
        result.append({
            "speaker": turn["speaker"],
            "text": turn["text"],
            "timestamp": turn["timestamp"].isoformat() if turn["timestamp"] else None,
        })
    return result
