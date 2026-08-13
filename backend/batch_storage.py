import json
import os
import sqlite3
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json_dump(value):
    return json.dumps(value, ensure_ascii=False)


def _json_load(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class BatchStorage:
    def __init__(self, database_path):
        self.database_path = database_path
        os.makedirs(os.path.dirname(database_path), exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS batch_jobs (
                    id TEXT PRIMARY KEY,
                    scenario TEXT NOT NULL,
                    requested_count INTEGER NOT NULL,
                    language TEXT NOT NULL,
                    roles_json TEXT NOT NULL,
                    max_turns INTEGER NOT NULL,
                    gap_ms INTEGER NOT NULL,
                    role_voice_map_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    error TEXT,
                    zip_filename TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS batch_items (
                    job_id TEXT NOT NULL,
                    item_index INTEGER NOT NULL,
                    variant_json TEXT,
                    script_json TEXT,
                    audio_filename TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    deepseek_request_id TEXT,
                    minimax_trace_ids_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, item_index),
                    FOREIGN KEY (job_id) REFERENCES batch_jobs(id) ON DELETE CASCADE
                );
                """
            )
            connection.execute(
                """
                UPDATE batch_jobs
                SET status = 'failed', stage = 'interrupted',
                    error = 'Backend restarted before the batch completed', updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (_now(),),
            )

    def create_job(self, job_id, payload):
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO batch_jobs (
                    id, scenario, requested_count, language, roles_json,
                    max_turns, gap_ms, role_voice_map_json, status, stage,
                    error, zip_filename, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 'queued', NULL, NULL, ?, ?)
                """,
                (
                    job_id,
                    payload["scenario"],
                    payload["count"],
                    payload["language"],
                    _json_dump(payload["roles"]),
                    payload["max_turns"],
                    payload["gap_ms"],
                    _json_dump(payload["role_voice_map"]),
                    now,
                    now,
                ),
            )

    def create_items(self, job_id, variants):
        now = _now()
        with self._connect() as connection:
            connection.execute("DELETE FROM batch_items WHERE job_id = ?", (job_id,))
            connection.executemany(
                """
                INSERT INTO batch_items (
                    job_id, item_index, variant_json, script_json, audio_filename,
                    status, error, deepseek_request_id, minimax_trace_ids_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, NULL, NULL, 'queued', NULL, NULL, NULL, ?, ?)
                """,
                [
                    (job_id, index, _json_dump(variant), now, now)
                    for index, variant in enumerate(variants)
                ],
            )

    def update_job(self, job_id, **changes):
        if not changes:
            return
        allowed = {"status", "stage", "error", "zip_filename"}
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError(f"Unsupported batch job fields: {sorted(invalid)}")
        changes["updated_at"] = _now()
        assignments = ", ".join(f"{field} = ?" for field in changes)
        values = list(changes.values()) + [job_id]
        with self._connect() as connection:
            connection.execute(
                f"UPDATE batch_jobs SET {assignments} WHERE id = ?", values
            )

    def update_item(self, job_id, item_index, **changes):
        if not changes:
            return
        json_fields = {"variant", "script", "minimax_trace_ids"}
        column_names = {
            "variant": "variant_json",
            "script": "script_json",
            "minimax_trace_ids": "minimax_trace_ids_json",
        }
        allowed = {
            "variant",
            "script",
            "audio_filename",
            "status",
            "error",
            "deepseek_request_id",
            "minimax_trace_ids",
        }
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError(f"Unsupported batch item fields: {sorted(invalid)}")

        normalized = {}
        for field, value in changes.items():
            column = column_names.get(field, field)
            normalized[column] = _json_dump(value) if field in json_fields else value
        normalized["updated_at"] = _now()
        assignments = ", ".join(f"{field} = ?" for field in normalized)
        values = list(normalized.values()) + [job_id, item_index]
        with self._connect() as connection:
            connection.execute(
                f"""
                UPDATE batch_items SET {assignments}
                WHERE job_id = ? AND item_index = ?
                """,
                values,
            )

    def get_job(self, job_id):
        with self._connect() as connection:
            job_row = connection.execute(
                "SELECT * FROM batch_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job_row is None:
                return None
            item_rows = connection.execute(
                """
                SELECT * FROM batch_items
                WHERE job_id = ? ORDER BY item_index
                """,
                (job_id,),
            ).fetchall()
        return self._serialize_job(job_row, item_rows)

    def _serialize_job(self, row, item_rows):
        items = []
        for item in item_rows:
            audio_filename = item["audio_filename"]
            items.append(
                {
                    "index": item["item_index"],
                    "status": item["status"],
                    "variant": _json_load(item["variant_json"], {}),
                    "script": _json_load(item["script_json"], None),
                    "audio_url": (
                        f"/api/download/{audio_filename}" if audio_filename else None
                    ),
                    "error": item["error"],
                    "request_id": item["deepseek_request_id"],
                    "trace_ids": _json_load(item["minimax_trace_ids_json"], []),
                }
            )

        requested_count = row["requested_count"]
        script_count = sum(item["script"] is not None for item in items)
        completed_count = sum(item["status"] == "completed" for item in items)
        failed_count = sum(item["status"] == "failed" for item in items)
        completed_units = script_count + completed_count
        total_units = max(1, requested_count * 2)
        progress_percent = min(100, round(completed_units / total_units * 100))
        if row["status"] in {"completed", "partial_failed", "failed"}:
            progress_percent = 100

        return {
            "job_id": row["id"],
            "scenario": row["scenario"],
            "requested_count": requested_count,
            "language": row["language"],
            "roles": _json_load(row["roles_json"], []),
            "max_turns": row["max_turns"],
            "gap_ms": row["gap_ms"],
            "role_voice_map": _json_load(row["role_voice_map_json"], {}),
            "status": row["status"],
            "stage": row["stage"],
            "error": row["error"],
            "script_count": script_count,
            "completed_count": completed_count,
            "failed_count": failed_count,
            "progress_percent": progress_percent,
            "zip_url": (
                f"/api/download/{row['zip_filename']}"
                if row["zip_filename"]
                else None
            ),
            "items": items,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
