"""Blob-backed store for dynamically provisioned chatbots.

This is the runtime source of truth for bots created through the external provisioning
API (`POST /provisioning/chatbots`). It mirrors the shape of :class:`ChatbotPromptStore`
so the wiring, container handling, and serialization stay consistent across stores.

ISOLATION INVARIANT: this store only ever contains dynamic bots. The 18 built-in bots
live in source code (KNOWN_CHATBOT_NAMES / CHATBOT_PROMPT_MODULES / the frontend registry)
and are never written here, never read from here, and never affected by it. Reserved-name
enforcement that keeps the two worlds apart lives in the provisioning layer.
"""

import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContentSettings

from approaches.chatbot_prompt_registry import normalize_chatbot_name
from prepdocslib.blobmanager import BlobManager

logger = logging.getLogger(__name__)

CHATBOT_REGISTRY_CONTAINER = "chatbot-registry"
CHATBOT_REGISTRY_PREFIX = "bots"

# number_sessions sentinel for unlimited (Enterprise plan).
UNLIMITED_SESSIONS = -1


@dataclass(frozen=True)
class ChatbotRegistryRecord:
    """A single dynamically provisioned chatbot.

    ``bot_name`` is the immutable primary key / route slug. ``display_name`` and everything
    below it are mutable via the provisioning ``update`` operation. The nested behavior
    objects (modes/design/qa/tutor/assessment/features/login and the per-language string
    maps) are stored verbatim as received; their precise schema is finalized with the
    upstream contract before they drive prompt/frontend behavior.
    """

    bot_name: str
    display_name: str
    active: bool
    created_at: str
    updated_at: str
    plan: Optional[str] = None
    number_sessions: int = UNLIMITED_SESSIONS
    ansprache: Optional[str] = None
    llm: Optional[str] = None
    prompt: str = ""
    modes: dict[str, Any] = field(default_factory=dict)
    design: dict[str, Any] = field(default_factory=dict)
    languages: list[str] = field(default_factory=list)
    greeting: dict[str, str] = field(default_factory=dict)
    disclaimer: dict[str, str] = field(default_factory=dict)
    flagged: dict[str, str] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    login: dict[str, Any] = field(default_factory=dict)
    qa: dict[str, Any] = field(default_factory=dict)
    tutor: dict[str, Any] = field(default_factory=dict)
    assessment: dict[str, Any] = field(default_factory=dict)
    last_session_id: Optional[str] = None


def format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class ChatbotRegistryStore:
    def __init__(
        self,
        *,
        blob_manager: BlobManager,
        container: str = CHATBOT_REGISTRY_CONTAINER,
        record_prefix: str = CHATBOT_REGISTRY_PREFIX,
    ):
        self.blob_manager = blob_manager
        self.container = container
        self.record_prefix = record_prefix.strip("/").strip()

    async def ensure_container_exists(self):
        container_client = self.blob_manager.blob_service_client.get_container_client(self.container)
        if not await container_client.exists():
            await container_client.create_container()
        return container_client

    def get_record_blob_name(self, bot_name: str) -> str:
        normalized_name = normalize_chatbot_name(bot_name)
        if normalized_name is None:
            raise ValueError("A valid chatbot name is required.")
        return f"{self.record_prefix}/{normalized_name}.json"

    async def load_json_blob(self, blob_name: str) -> dict | None:
        result = await self.blob_manager.download_blob(blob_name, container=self.container)
        if result is None:
            return None

        content, _properties = result
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Invalid JSON payload for blob %s", blob_name)
            return None
        if not isinstance(payload, dict):
            logger.warning("Unexpected JSON payload type for blob %s", blob_name)
            return None
        return payload

    async def save_json_blob(self, blob_name: str, payload: dict) -> None:
        container_client = await self.ensure_container_exists()
        await container_client.upload_blob(
            blob_name,
            io.BytesIO(json.dumps(payload, ensure_ascii=True).encode("utf-8")),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )

    async def delete_blob_if_exists(self, blob_name: str) -> None:
        container_client = await self.ensure_container_exists()
        try:
            await container_client.delete_blob(blob_name, delete_snapshots="include")
        except ResourceNotFoundError:
            logger.debug("Blob already removed from %s: %s", self.container, blob_name)

    def serialize_record(self, record: ChatbotRegistryRecord) -> dict[str, Any]:
        return {
            "botName": record.bot_name,
            "displayName": record.display_name,
            "active": record.active,
            "plan": record.plan,
            "numberSessions": record.number_sessions,
            "ansprache": record.ansprache,
            "llm": record.llm,
            "prompt": record.prompt,
            "modes": record.modes,
            "design": record.design,
            "languages": record.languages,
            "greeting": record.greeting,
            "disclaimer": record.disclaimer,
            "flagged": record.flagged,
            "features": record.features,
            "login": record.login,
            "qa": record.qa,
            "tutor": record.tutor,
            "assessment": record.assessment,
            "lastSessionId": record.last_session_id,
            "createdAt": record.created_at,
            "updatedAt": record.updated_at,
        }

    def deserialize_record(self, bot_name: str, payload: dict | None) -> ChatbotRegistryRecord | None:
        if payload is None:
            return None
        normalized_name = normalize_chatbot_name(bot_name)
        if normalized_name is None:
            return None
        created_at = payload.get("createdAt")
        updated_at = payload.get("updatedAt")
        if not (isinstance(created_at, str) and created_at and isinstance(updated_at, str) and updated_at):
            logger.warning("Incomplete chatbot registry payload for %s", normalized_name)
            return None
        payload_bot_name = payload.get("botName")
        if isinstance(payload_bot_name, str) and normalize_chatbot_name(payload_bot_name) not in {
            None,
            normalized_name,
        }:
            logger.warning("Registry blob botName mismatch for %s", normalized_name)
            return None

        number_sessions = payload.get("numberSessions", UNLIMITED_SESSIONS)
        if not isinstance(number_sessions, int):
            number_sessions = UNLIMITED_SESSIONS

        def as_dict(value: Any) -> dict[str, Any]:
            return value if isinstance(value, dict) else {}

        def as_list(value: Any) -> list[str]:
            return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

        display_name = payload.get("displayName")
        plan = payload.get("plan")
        ansprache = payload.get("ansprache")
        llm = payload.get("llm")
        prompt = payload.get("prompt")
        last_session_id = payload.get("lastSessionId")
        return ChatbotRegistryRecord(
            bot_name=normalized_name,
            display_name=display_name if isinstance(display_name, str) and display_name else normalized_name,
            active=bool(payload.get("active", False)),
            created_at=created_at,
            updated_at=updated_at,
            plan=plan if isinstance(plan, str) else None,
            number_sessions=number_sessions,
            ansprache=ansprache if isinstance(ansprache, str) else None,
            llm=llm if isinstance(llm, str) else None,
            prompt=prompt if isinstance(prompt, str) else "",
            modes=as_dict(payload.get("modes")),
            design=as_dict(payload.get("design")),
            languages=as_list(payload.get("languages")),
            greeting=as_dict(payload.get("greeting")),
            disclaimer=as_dict(payload.get("disclaimer")),
            flagged=as_dict(payload.get("flagged")),
            features=as_dict(payload.get("features")),
            login=as_dict(payload.get("login")),
            qa=as_dict(payload.get("qa")),
            tutor=as_dict(payload.get("tutor")),
            assessment=as_dict(payload.get("assessment")),
            last_session_id=last_session_id if isinstance(last_session_id, str) else None,
        )

    async def load_record(self, bot_name: str) -> ChatbotRegistryRecord | None:
        normalized_name = normalize_chatbot_name(bot_name)
        if normalized_name is None:
            return None
        payload = await self.load_json_blob(self.get_record_blob_name(normalized_name))
        return self.deserialize_record(normalized_name, payload)

    async def list_records(self) -> dict[str, ChatbotRegistryRecord]:
        container_client = self.blob_manager.blob_service_client.get_container_client(self.container)
        if not await container_client.exists():
            return {}

        records: dict[str, ChatbotRegistryRecord] = {}
        async for blob in container_client.list_blobs(name_starts_with=f"{self.record_prefix}/"):
            blob_name = getattr(blob, "name", None)
            if not blob_name:
                continue
            payload = await self.load_json_blob(blob_name)
            bot_name = blob_name.rsplit("/", 1)[-1].removesuffix(".json")
            record = self.deserialize_record(bot_name, payload)
            if record is not None:
                records[record.bot_name] = record
        return records

    async def save_record(self, bot_name: str, *, fields: dict[str, Any]) -> ChatbotRegistryRecord:
        """Upsert a record. Preserves ``created_at`` across updates (mirrors save_prompt)."""
        normalized_name = normalize_chatbot_name(bot_name)
        if normalized_name is None:
            raise ValueError("A valid chatbot name is required.")

        existing = await self.load_record(normalized_name)
        now = format_utc(datetime.now(timezone.utc))
        record = ChatbotRegistryRecord(
            bot_name=normalized_name,
            display_name=fields.get("display_name") or (existing.display_name if existing else normalized_name),
            active=bool(fields["active"]) if "active" in fields else (existing.active if existing else False),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            plan=fields.get("plan", existing.plan if existing else None),
            number_sessions=fields.get(
                "number_sessions", existing.number_sessions if existing else UNLIMITED_SESSIONS
            ),
            ansprache=fields.get("ansprache", existing.ansprache if existing else None),
            llm=fields.get("llm", existing.llm if existing else None),
            prompt=fields.get("prompt", existing.prompt if existing else ""),
            modes=fields.get("modes", existing.modes if existing else {}),
            design=fields.get("design", existing.design if existing else {}),
            languages=fields.get("languages", existing.languages if existing else []),
            greeting=fields.get("greeting", existing.greeting if existing else {}),
            disclaimer=fields.get("disclaimer", existing.disclaimer if existing else {}),
            flagged=fields.get("flagged", existing.flagged if existing else {}),
            features=fields.get("features", existing.features if existing else {}),
            login=fields.get("login", existing.login if existing else {}),
            qa=fields.get("qa", existing.qa if existing else {}),
            tutor=fields.get("tutor", existing.tutor if existing else {}),
            assessment=fields.get("assessment", existing.assessment if existing else {}),
            last_session_id=fields.get("last_session_id", existing.last_session_id if existing else None),
        )
        await self.save_json_blob(self.get_record_blob_name(normalized_name), self.serialize_record(record))
        return record

    async def set_active(self, bot_name: str, active: bool) -> ChatbotRegistryRecord | None:
        existing = await self.load_record(bot_name)
        if existing is None:
            return None
        return await self.save_record(bot_name, fields={"active": active})

    async def delete_record(self, bot_name: str) -> bool:
        normalized_name = normalize_chatbot_name(bot_name)
        if normalized_name is None:
            return False
        existing = await self.load_record(normalized_name)
        if existing is None:
            return False
        await self.delete_blob_if_exists(self.get_record_blob_name(normalized_name))
        return True
