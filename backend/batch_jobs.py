import json
import os
import re
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

import config
import deepseek_client
import minimax_client
from audio_assembler import AudioAssemblyError, assemble_dialogue
from batch_storage import BatchStorage


FINAL_JOB_STATUSES = {"completed", "partial_failed", "failed"}


class BatchJobError(Exception):
    pass


def _safe_filename(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")
    return value[:60] or "dialogue"


def _script_text(turns):
    return " ".join(str(turn.get("text", "")).lower().strip() for turn in turns)


def _script_similarity(first, second):
    return SequenceMatcher(None, _script_text(first), _script_text(second)).ratio()


class BatchJobManager:
    def __init__(self):
        self.storage = BatchStorage(config.BATCH_DATABASE_PATH)
        self.executor = ThreadPoolExecutor(max_workers=config.BATCH_JOB_CONCURRENCY)

    def create_job(self, payload):
        job_id = uuid.uuid4().hex
        self.storage.create_job(job_id, payload)
        self.executor.submit(self._run_job, job_id)
        return self.storage.get_job(job_id)

    def get_job(self, job_id):
        return self.storage.get_job(job_id)

    def retry_failed(self, job_id):
        job = self.storage.get_job(job_id)
        if job is None:
            raise BatchJobError("Batch job not found")
        if job["status"] not in FINAL_JOB_STATUSES:
            raise BatchJobError("Batch job is still running")
        failed_items = [item for item in job["items"] if item["status"] == "failed"]
        if not failed_items:
            raise BatchJobError("This batch has no failed items to retry")
        self.storage.update_job(job_id, status="queued", stage="retrying", error=None)
        self.executor.submit(self._retry_items, job_id, [item["index"] for item in failed_items])
        return self.storage.get_job(job_id)

    def _run_job(self, job_id):
        job = self.storage.get_job(job_id)
        try:
            self.storage.update_job(job_id, status="running", stage="planning", error=None)
            variants = deepseek_client.generate_scenario_variants(
                job["scenario"], job["requested_count"], language=job["language"]
            )
            self.storage.create_items(job_id, variants)
            self.storage.update_job(job_id, stage="generating_scripts")
            self._generate_scripts(job_id, list(range(job["requested_count"])))
            refreshed = self.storage.get_job(job_id)
            script_indexes = [
                item["index"] for item in refreshed["items"] if item["script"] is not None
            ]
            if not script_indexes:
                raise BatchJobError("All dialogue scripts failed to generate")
            self.storage.update_job(job_id, stage="generating_audio")
            self._generate_audio(job_id, script_indexes)
            self._finalize_job(job_id)
        except Exception as exc:
            self.storage.update_job(
                job_id, status="failed", stage="failed", error=str(exc)
            )

    def _retry_items(self, job_id, indexes):
        try:
            job = self.storage.get_job(job_id)
            missing_scripts = [
                item["index"]
                for item in job["items"]
                if item["index"] in indexes and item["script"] is None
            ]
            if missing_scripts:
                self.storage.update_job(job_id, status="running", stage="generating_scripts")
                self._generate_scripts(job_id, missing_scripts)
            refreshed = self.storage.get_job(job_id)
            audio_indexes = [
                item["index"]
                for item in refreshed["items"]
                if item["index"] in indexes and item["script"] is not None
            ]
            self.storage.update_job(job_id, status="running", stage="generating_audio")
            self._generate_audio(job_id, audio_indexes)
            self._finalize_job(job_id)
        except Exception as exc:
            self.storage.update_job(
                job_id, status="failed", stage="failed", error=str(exc)
            )

    def _generate_scripts(self, job_id, indexes):
        job = self.storage.get_job(job_id)
        max_workers = max(1, min(config.DEEPSEEK_BATCH_CONCURRENCY, len(indexes)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._generate_script_item, job, index): index
                for index in indexes
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    self.storage.update_item(
                        job_id, index, status="failed", error=str(exc)
                    )

    def _generate_script_item(self, job, index):
        item = next(item for item in job["items"] if item["index"] == index)
        self.storage.update_item(job["job_id"], index, status="scripting", error=None)
        variant = item["variant"]
        scenario = self._variant_prompt(job["scenario"], variant)
        generated = deepseek_client.generate_dialogue_script(
            scenario,
            job["roles"],
            max_turns=job["max_turns"],
            language=job["language"],
        )
        turns = generated["turns"]

        existing_scripts = [
            other["script"]["turns"]
            for other in self.storage.get_job(job["job_id"])["items"]
            if other["script"] is not None and other["index"] != index
        ]
        if any(
            _script_similarity(turns, existing) >= config.BATCH_SIMILARITY_THRESHOLD
            for existing in existing_scripts
        ):
            scenario += (
                "\nThe first draft was too similar to another batch item. Regenerate it "
                "with a clearly different opening, customer context, question sequence, "
                "and resolution path while preserving the same core topic."
            )
            generated = deepseek_client.generate_dialogue_script(
                scenario,
                job["roles"],
                max_turns=job["max_turns"],
                language=job["language"],
            )
            turns = generated["turns"]

        script = {
            "turns": turns,
            "model": generated.get("model", config.DEEPSEEK_MODEL),
            "usage": generated.get("usage", {}),
        }
        self.storage.update_item(
            job["job_id"],
            index,
            script=script,
            status="script_ready",
            error=None,
            deepseek_request_id=generated.get("request_id"),
        )

    @staticmethod
    def _variant_prompt(base_scenario, variant):
        return (
            f"Base customer-service topic: {base_scenario}\n"
            "Generate a complete dialogue for this distinct batch variation:\n"
            f"Title: {variant.get('title', '')}\n"
            f"Customer profile: {variant.get('customer_profile', '')}\n"
            f"Trigger: {variant.get('trigger', '')}\n"
            f"Tone: {variant.get('tone', '')}\n"
            f"Goal: {variant.get('goal', '')}\n"
            "Stay within the base topic, but make the opening, details, questions, and "
            "resolution meaningfully different from other possible variations."
        )

    def _generate_audio(self, job_id, indexes):
        if not indexes:
            return
        max_workers = max(1, min(config.MINIMAX_BATCH_CONCURRENCY, len(indexes)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._generate_audio_item, job_id, index): index
                for index in indexes
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    self.storage.update_item(
                        job_id, index, status="failed", error=str(exc)
                    )

    def _generate_audio_item(self, job_id, index):
        job = self.storage.get_job(job_id)
        item = next(item for item in job["items"] if item["index"] == index)
        if item["script"] is None:
            raise BatchJobError("Cannot generate audio without a script")
        self.storage.update_item(job_id, index, status="generating_audio", error=None)
        tts_language = config.SUPPORTED_LANGUAGES[job["language"]]["minimax"]
        synthesis_results = []
        for turn in item["script"]["turns"]:
            synthesis_results.append(
                minimax_client.synthesize_speech(
                    turn["text"],
                    job["role_voice_map"][turn["speaker"]],
                    language_boost=tts_language,
                )
            )

        relative_directory = os.path.join("batches", job_id)
        absolute_directory = os.path.join(config.OUTPUT_DIR, relative_directory)
        os.makedirs(absolute_directory, exist_ok=True)
        title = item["variant"].get("title") or f"dialogue_{index + 1}"
        filename = f"{index + 1:02d}_{_safe_filename(title)}.mp3"
        relative_filename = os.path.join(relative_directory, filename)
        absolute_filename = os.path.join(config.OUTPUT_DIR, relative_filename)
        gaps_ms = [job["gap_ms"]] * max(0, len(synthesis_results) - 1)
        assemble_dialogue(
            [result["audio"] for result in synthesis_results],
            gaps_ms,
            absolute_filename,
        )

        metadata_filename = os.path.splitext(absolute_filename)[0] + ".json"
        with open(metadata_filename, "w", encoding="utf-8") as metadata_file:
            json.dump(
                {
                    "scenario": job["scenario"],
                    "variant": item["variant"],
                    "language": job["language"],
                    "roles": job["roles"],
                    "role_voice_map": job["role_voice_map"],
                    "gap_ms": job["gap_ms"],
                    "turns": item["script"]["turns"],
                },
                metadata_file,
                ensure_ascii=False,
                indent=2,
            )

        self.storage.update_item(
            job_id,
            index,
            audio_filename=relative_filename,
            status="completed",
            error=None,
            minimax_trace_ids=[
                result["trace_id"]
                for result in synthesis_results
                if result.get("trace_id")
            ],
        )

    def _finalize_job(self, job_id):
        job = self.storage.get_job(job_id)
        completed = [item for item in job["items"] if item["status"] == "completed"]
        failed = [item for item in job["items"] if item["status"] == "failed"]
        zip_filename = self._create_archive(job) if completed else None
        if completed and failed:
            status = "partial_failed"
        elif completed:
            status = "completed"
        else:
            status = "failed"
        self.storage.update_job(
            job_id,
            status=status,
            stage="completed" if completed else "failed",
            error=(f"{len(failed)} item(s) failed" if failed else None),
            zip_filename=zip_filename,
        )

    @staticmethod
    def _create_archive(job):
        relative_directory = os.path.join("batches", job["job_id"])
        absolute_directory = os.path.join(config.OUTPUT_DIR, relative_directory)
        os.makedirs(absolute_directory, exist_ok=True)
        archive_name = f"batch_{job['job_id']}.zip"
        relative_archive = os.path.join(relative_directory, archive_name)
        absolute_archive = os.path.join(config.OUTPUT_DIR, relative_archive)
        manifest = {
            "job_id": job["job_id"],
            "scenario": job["scenario"],
            "language": job["language"],
            "roles": job["roles"],
            "role_voice_map": job["role_voice_map"],
            "items": job["items"],
        }
        manifest_path = os.path.join(absolute_directory, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)

        with zipfile.ZipFile(absolute_archive, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename in os.listdir(absolute_directory):
                if filename == archive_name:
                    continue
                file_path = os.path.join(absolute_directory, filename)
                if os.path.isfile(file_path):
                    archive.write(file_path, arcname=filename)
        return relative_archive


batch_job_manager = BatchJobManager()
