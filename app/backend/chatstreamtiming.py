import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob.aio import BlobServiceClient

log = logging.getLogger("chat_stream_timing")


def utc_now_isoformat() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_seconds(seconds: float) -> float:
    return round(max(seconds, 0.0), 4)


def create_chat_timing_session_id(session_state: Any, chat_session_id: Optional[str] = None) -> str:
    if isinstance(chat_session_id, str) and chat_session_id.strip():
        return chat_session_id.strip()

    if isinstance(session_state, str) and session_state.strip():
        return session_state

    if session_state is not None:
        try:
            serialized_state = json.dumps(session_state, sort_keys=True, default=str)
        except TypeError:
            serialized_state = str(session_state)
        return str(uuid.uuid5(uuid.NAMESPACE_URL, serialized_state))

    return str(uuid.uuid4())


class ChatStreamTimingContext:
    def __init__(
        self,
        session_id: str,
        request_id: Optional[str] = None,
        request_started_perf_counter: Optional[float] = None,
    ):
        self.session_id = session_id
        self.request_id = request_id or str(uuid.uuid4())
        self.request_started_at_utc = utc_now_isoformat()
        self.request_started_perf_counter = (
            request_started_perf_counter if request_started_perf_counter is not None else time.perf_counter()
        )
        self.step_durations_seconds: dict[str, float] = {}
        self.last_step_checkpoint_perf_counter = self.request_started_perf_counter
        self.api_to_llm_stream_start_seconds: Optional[float] = None
        self.status = "in_progress"
        self.error: Optional[str] = None
        self.llm_stream_started = False

    def record_step(
        self,
        step_name: str,
        ended_perf_counter: Optional[float] = None,
    ) -> None:
        ended_at = ended_perf_counter if ended_perf_counter is not None else time.perf_counter()
        duration_seconds = max(ended_at - self.last_step_checkpoint_perf_counter, 0.0)
        self.step_durations_seconds[step_name] = self.step_durations_seconds.get(step_name, 0.0) + duration_seconds
        self.last_step_checkpoint_perf_counter = ended_at

    def mark_llm_stream_started(self, stream_started_perf_counter: Optional[float] = None) -> None:
        if not self.llm_stream_started:
            self.llm_stream_started = True
            stream_started_at = stream_started_perf_counter if stream_started_perf_counter is not None else time.perf_counter()
            self.api_to_llm_stream_start_seconds = max(stream_started_at - self.request_started_perf_counter, 0.0)

    def mark_error(self, error: Exception) -> None:
        self.status = "error"
        self.error = str(error)

    def mark_completed(self) -> None:
        if self.status == "in_progress":
            self.status = "completed"

    def build_rounded_step_durations(self, total_time_seconds: Optional[float]) -> dict[str, float]:
        items = list(self.step_durations_seconds.items())
        if not items:
            return {}

        if total_time_seconds is None:
            return {name: to_seconds(duration) for name, duration in items}

        rounded_total = to_seconds(total_time_seconds)
        rounded_steps = {name: to_seconds(duration) for name, duration in items}
        rounded_sum = to_seconds(sum(rounded_steps.values()))

        last_step_name = items[-1][0]
        adjusted_last = rounded_steps[last_step_name] + (rounded_total - rounded_sum)
        rounded_steps[last_step_name] = to_seconds(max(adjusted_last, 0.0))

        return rounded_steps

    def to_payload(self) -> dict[str, Any]:
        total_time = (
            to_seconds(self.api_to_llm_stream_start_seconds)
            if self.api_to_llm_stream_start_seconds is not None
            else None
        )
        rounded_steps = self.build_rounded_step_durations(self.api_to_llm_stream_start_seconds)

        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "request_id": self.request_id,
            "request_started_at_utc": self.request_started_at_utc,
            "recorded_at_utc": utc_now_isoformat(),
            "status": self.status,
            "step_durations_seconds": rounded_steps,
            "total_time_taken_to_generate_response": (
                {"api_to_llm_stream_start_seconds": total_time} if total_time is not None else {}
            ),
        }
        if self.error:
            payload["error"] = self.error
        return payload


class ChatStreamTimingLogWriter:
    def __init__(
        self,
        logfile_name: str,
        container_name: str = "logfiles",
        blob_service_client: Optional[BlobServiceClient] = None,
    ):
        normalized_logfile_name = logfile_name.strip()
        if normalized_logfile_name.lower().endswith(".json"):
            normalized_logfile_name = normalized_logfile_name[:-5]
        normalized_logfile_name = normalized_logfile_name or "chat_stream_timings"

        self.logfile_name = f"{normalized_logfile_name}.json"
        self.container_name = container_name
        self.blob_service_client = blob_service_client
        self.file_write_lock = asyncio.Lock()

    def configure_blob_service_client(self, blob_service_client: BlobServiceClient) -> None:
        self.blob_service_client = blob_service_client

    async def append_timing(self, timing_context: ChatStreamTimingContext) -> None:
        if self.blob_service_client is None:
            log.warning("Blob service client not configured for chat stream timing writer; skipping timing log write.")
            return

        async with self.file_write_lock:
            await self.append_timing_to_blob(timing_context.to_payload())

    async def append_timing_to_blob(self, request_payload: dict[str, Any]) -> None:
        session_id = request_payload["session_id"]

        if self.blob_service_client is None:
            return

        container_client = self.blob_service_client.get_container_client(self.container_name)
        if not await container_client.exists():
            await container_client.create_container()

        blob_client = container_client.get_blob_client(self.logfile_name)
        log_document: dict[str, Any] = {}
        try:
            download_response = await blob_client.download_blob()
            blob_content_bytes = await download_response.readall()
            blob_content = blob_content_bytes.decode("utf-8")
            log_document = json.loads(blob_content)
        except ResourceNotFoundError:
            log_document = {}
        except json.JSONDecodeError:
            log.warning(
                "Chat stream timing log blob is not valid JSON, resetting: %s/%s",
                self.container_name,
                self.logfile_name,
            )
            log_document = {}

        log_document["logfile_name"] = self.logfile_name
        sessions = log_document.setdefault("sessions", {})
        session_payload = sessions.setdefault(
            session_id,
            {
                "session_id": session_id,
                "created_at_utc": request_payload["request_started_at_utc"],
                "last_updated_at_utc": request_payload["recorded_at_utc"],
                "requests": [],
            },
        )
        session_payload["last_updated_at_utc"] = request_payload["recorded_at_utc"]
        requests = session_payload.setdefault("requests", [])
        requests.append(request_payload)

        serialized_payload = json.dumps(log_document, ensure_ascii=False, indent=2)
        await blob_client.upload_blob(serialized_payload, overwrite=True)
