import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContentSettings

from approaches.chatbot_prompt_registry import normalize_chatbot_name
from embed_rules import normalize_rules
from prepdocslib.blobmanager import BlobManager

logger = logging.getLogger(__name__)

CHATBOT_EMBED_CONFIG_CONTAINER = "chatbot-embed-config"
CHATBOT_EMBED_CONFIG_PREFIX = "embed"


def format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class ChatbotEmbedConfig:
    chatbot_name: str
    allowed_rules: list[str] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class ChatbotEmbedConfigStore:
    """Blob-backed, admin-editable per-chatbot embed whitelist (mirrors ChatbotPromptStore)."""

    def __init__(
        self,
        *,
        blob_manager: BlobManager,
        container: str = CHATBOT_EMBED_CONFIG_CONTAINER,
        config_prefix: str = CHATBOT_EMBED_CONFIG_PREFIX,
    ):
        self.blob_manager = blob_manager
        self.container = container
        self.config_prefix = config_prefix.strip("/").strip()

    async def ensure_container_exists(self):
        container_client = self.blob_manager.blob_service_client.get_container_client(self.container)
        if not await container_client.exists():
            await container_client.create_container()
        return container_client

    def get_config_blob_name(self, chatbot_name: str) -> str:
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            raise ValueError("A valid chatbot name is required.")
        return f"{self.config_prefix}/{normalized_name}.json"

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

    def deserialize_config(self, chatbot_name: str, payload: dict | None) -> ChatbotEmbedConfig | None:
        if payload is None:
            return None
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            return None
        raw_rules = payload.get("allowedRules")
        if not isinstance(raw_rules, list):
            raw_rules = []
        rules = normalize_rules([rule for rule in raw_rules if isinstance(rule, str)])
        created_at = payload.get("createdAt")
        updated_at = payload.get("updatedAt")
        return ChatbotEmbedConfig(
            chatbot_name=normalized_name,
            allowed_rules=rules,
            created_at=created_at if isinstance(created_at, str) else None,
            updated_at=updated_at if isinstance(updated_at, str) else None,
        )

    async def load_config(self, chatbot_name: str) -> ChatbotEmbedConfig | None:
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            return None
        payload = await self.load_json_blob(self.get_config_blob_name(normalized_name))
        return self.deserialize_config(normalized_name, payload)

    async def load_allowed_rules(self, chatbot_name: str) -> list[str]:
        config = await self.load_config(chatbot_name)
        return list(config.allowed_rules) if config is not None else []

    async def save_rules(self, chatbot_name: str, rules: list[str]) -> ChatbotEmbedConfig:
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            raise ValueError("A valid chatbot name is required.")
        normalized_rules = normalize_rules([rule for rule in rules if isinstance(rule, str)])

        # An empty whitelist means "allow all" — store nothing rather than an empty record.
        if not normalized_rules:
            await self.delete_blob_if_exists(self.get_config_blob_name(normalized_name))
            return ChatbotEmbedConfig(chatbot_name=normalized_name, allowed_rules=[])

        existing = await self.load_config(normalized_name)
        now = format_utc(datetime.now(timezone.utc))
        config = ChatbotEmbedConfig(
            chatbot_name=normalized_name,
            allowed_rules=normalized_rules,
            created_at=existing.created_at if existing and existing.created_at else now,
            updated_at=now,
        )
        await self.save_json_blob(
            self.get_config_blob_name(normalized_name),
            {
                "chatbotName": config.chatbot_name,
                "allowedRules": config.allowed_rules,
                "createdAt": config.created_at,
                "updatedAt": config.updated_at,
            },
        )
        return config

    async def delete_config(self, chatbot_name: str) -> bool:
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            return False
        existing = await self.load_config(normalized_name)
        if existing is None:
            return False
        await self.delete_blob_if_exists(self.get_config_blob_name(normalized_name))
        return True
