import json

import pytest
from azure.core.exceptions import ResourceNotFoundError

from chatstreamtiming import ChatStreamTimingContext, ChatStreamTimingLogWriter, create_chat_timing_session_id


class FakeDownloadResponse:
    def __init__(self, payload: str):
        self.payload = payload

    async def readall(self):
        return self.payload.encode("utf-8")


class FakeBlobClient:
    def __init__(self, container_storage: dict[str, str], blob_name: str):
        self.container_storage = container_storage
        self.blob_name = blob_name

    async def download_blob(self):
        if self.blob_name not in self.container_storage:
            raise ResourceNotFoundError("not found")
        return FakeDownloadResponse(self.container_storage[self.blob_name])

    async def upload_blob(self, payload: str, overwrite: bool = False):
        self.container_storage[self.blob_name] = payload


class FakeContainerClient:
    def __init__(self, storage: dict[str, dict[str, str]], container_name: str):
        self.storage = storage
        self.container_name = container_name

    async def exists(self):
        return self.container_name in self.storage

    async def create_container(self):
        self.storage.setdefault(self.container_name, {})

    def get_blob_client(self, blob_name: str):
        container_storage = self.storage.setdefault(self.container_name, {})
        return FakeBlobClient(container_storage, blob_name)


class FakeBlobServiceClient:
    def __init__(self):
        self.storage: dict[str, dict[str, str]] = {}

    def get_container_client(self, container_name: str):
        return FakeContainerClient(self.storage, container_name)


def test_create_chat_timing_session_id_uses_existing_string_state():
    session_id = create_chat_timing_session_id("existing-session-id")
    assert session_id == "existing-session-id"


def test_create_chat_timing_session_id_prefers_chat_session_id():
    session_id = create_chat_timing_session_id(None, chat_session_id="frontend-session-id")
    assert session_id == "frontend-session-id"


@pytest.mark.asyncio
async def test_chat_stream_timing_log_writer_groups_requests_by_session():
    blob_service_client = FakeBlobServiceClient()
    writer = ChatStreamTimingLogWriter("chat_stream_timings", blob_service_client=blob_service_client)
    session_id = create_chat_timing_session_id({"conversation_id": 1234})

    first_request = ChatStreamTimingContext(session_id=session_id)
    first_request.record_step(
        "query_rewrite_seconds",
        ended_perf_counter=first_request.request_started_perf_counter + 0.12,
    )
    first_request.mark_llm_stream_started(stream_started_perf_counter=first_request.request_started_perf_counter + 0.12)
    first_request.mark_completed()
    await writer.append_timing(first_request)

    second_request = ChatStreamTimingContext(session_id=session_id)
    second_request.record_step(
        "query_rewrite_seconds",
        ended_perf_counter=second_request.request_started_perf_counter + 0.08,
    )
    second_request.mark_llm_stream_started(stream_started_perf_counter=second_request.request_started_perf_counter + 0.08)
    second_request.mark_completed()
    await writer.append_timing(second_request)

    blob_payload = blob_service_client.storage["logfiles"]["chat_stream_timings.json"]
    payload = json.loads(blob_payload)

    assert payload["logfile_name"] == "chat_stream_timings.json"
    assert "sessions" in payload
    assert session_id in payload["sessions"]
    session_payload = payload["sessions"][session_id]
    assert session_payload["session_id"] == session_id
    assert len(session_payload["requests"]) == 2
