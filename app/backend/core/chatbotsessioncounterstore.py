"""Blob-backed, multi-replica-safe cumulative session counter for DYNAMIC bots.

Quota enforcement (`number_sessions`) needs a session counter that stays correct across multiple
Azure Container Apps replicas. The intended store (Cosmos) is disabled in the active deployment, so
this uses Azure Blob with **ETag optimistic concurrency**: increments do a conditional PUT
(`If-Match` on the read ETag) and retry on a concurrent write, so no count is ever lost. Plain
read-modify-write (what the registry store does) would silently drop concurrent increments.

ISOLATION INVARIANT: only dynamic bots with a finite `number_sessions` cap ever reach this store.
Built-in bots and unlimited (-1) dynamic bots never touch it (the gate short-circuits first).
"""

import io
import json
import logging
from datetime import datetime, timezone

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.storage.blob import ContentSettings

from approaches.chatbot_prompt_registry import normalize_chatbot_name
from prepdocslib.blobmanager import BlobManager

logger = logging.getLogger(__name__)

CHATBOT_SESSION_COUNTERS_CONTAINER = "chatbot-session-counters"
CHATBOT_SESSION_COUNTERS_PREFIX = "counters"
# Bound on the optimistic-concurrency retry loop. Contention is per-bot, so this is generous.
MAX_INCREMENT_ATTEMPTS = 8


def format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class ChatbotSessionCounterStore:
    def __init__(
        self,
        *,
        blob_manager: BlobManager,
        container: str = CHATBOT_SESSION_COUNTERS_CONTAINER,
        counter_prefix: str = CHATBOT_SESSION_COUNTERS_PREFIX,
    ):
        self.blob_manager = blob_manager
        self.container = container
        self.counter_prefix = counter_prefix.strip("/").strip()

    def get_counter_blob_name(self, chatbot_name: str) -> str:
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            raise ValueError("A valid chatbot name is required.")
        return f"{self.counter_prefix}/{normalized_name}.json"

    def container_client(self):
        return self.blob_manager.blob_service_client.get_container_client(self.container)

    async def ensure_container_exists(self):
        container_client = self.container_client()
        if not await container_client.exists():
            await container_client.create_container()
        return container_client

    def parse_count(self, raw: bytes) -> int:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 0
        count = payload.get("count") if isinstance(payload, dict) else None
        return count if isinstance(count, int) and count >= 0 else 0

    def serialize(self, chatbot_name: str, count: int) -> io.BytesIO:
        payload = {
            "chatbotName": chatbot_name,
            "count": count,
            "updatedAt": format_utc(datetime.now(timezone.utc)),
        }
        return io.BytesIO(json.dumps(payload, ensure_ascii=True).encode("utf-8"))

    async def get_count(self, chatbot_name: str) -> int:
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            return 0
        container_client = self.container_client()
        if not await container_client.exists():
            return 0
        blob_client = container_client.get_blob_client(self.get_counter_blob_name(normalized_name))
        try:
            downloader = await blob_client.download_blob()
            raw = await downloader.readall()
        except ResourceNotFoundError:
            return 0
        return self.parse_count(raw)

    async def increment(self, chatbot_name: str) -> int:
        """Atomically add 1 to the bot's cumulative session count and return the new value."""
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            raise ValueError("A valid chatbot name is required.")
        container_client = await self.ensure_container_exists()
        blob_client = container_client.get_blob_client(self.get_counter_blob_name(normalized_name))
        content_settings = ContentSettings(content_type="application/json")

        for _ in range(MAX_INCREMENT_ATTEMPTS):
            try:
                downloader = await blob_client.download_blob()
                etag = downloader.properties.etag
                raw = await downloader.readall()
            except ResourceNotFoundError:
                # No counter yet — create it, but fail if a concurrent replica beat us to it.
                try:
                    await blob_client.upload_blob(
                        self.serialize(normalized_name, 1), overwrite=False, content_settings=content_settings
                    )
                    return 1
                except ResourceExistsError:
                    continue  # someone created it first — re-read and increment
            new_count = self.parse_count(raw) + 1
            try:
                await blob_client.upload_blob(
                    self.serialize(normalized_name, new_count),
                    overwrite=True,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                    content_settings=content_settings,
                )
                return new_count
            except ResourceModifiedError:
                continue  # a concurrent increment landed first — re-read and retry
        raise RuntimeError(f"Could not atomically increment session counter for {normalized_name}")
