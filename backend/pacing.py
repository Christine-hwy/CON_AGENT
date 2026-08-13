from datetime import datetime

from config import ESTIMATED_GAP_MAX_MS, ESTIMATED_GAP_MIN_MS, REAL_GAP_MAX_MS, REAL_GAP_MIN_MS


def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def compute_gaps(turns):
    """返回长度为 len(turns)-1 的间隔列表（毫秒），turns[i] 和 turns[i+1] 之间的停顿。"""
    has_timestamps = all(t.get("timestamp") for t in turns)
    if has_timestamps:
        return _gaps_from_timestamps(turns)
    return _gaps_from_text_length(turns)


def _gaps_from_timestamps(turns):
    gaps = []
    for i in range(len(turns) - 1):
        ts_a = turns[i]["timestamp"]
        ts_b = turns[i + 1]["timestamp"]
        if isinstance(ts_a, str):
            ts_a = datetime.fromisoformat(ts_a)
        if isinstance(ts_b, str):
            ts_b = datetime.fromisoformat(ts_b)
        delta_ms = (ts_b - ts_a).total_seconds() * 1000
        gaps.append(_clamp(delta_ms, REAL_GAP_MIN_MS, REAL_GAP_MAX_MS))
    return gaps


def _gaps_from_text_length(turns, chars_per_sec=4):
    gaps = []
    for i in range(len(turns) - 1):
        # 用下一句话的字数估算对方"反应"停顿：越短的应答，停顿越接近下限
        next_len = len(turns[i + 1]["text"])
        estimated_ms = (next_len / chars_per_sec) * 1000
        gaps.append(_clamp(estimated_ms, ESTIMATED_GAP_MIN_MS, ESTIMATED_GAP_MAX_MS))
    return gaps
