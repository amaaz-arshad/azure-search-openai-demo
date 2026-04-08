import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContentSettings

from approaches.chatbot_prompt_registry import normalize_chatbot_name
from prepdocslib.blobmanager import BlobManager

logger = logging.getLogger(__name__)

CHATBOT_PROMPTS_CONTAINER = "chatbot-prompts"
CHATBOT_PROMPTS_PREFIX = "prompts"


@dataclass(frozen=True)
class ChatbotPromptOverride:
    chatbot_name: str
    prompt: str
    created_at: str
    updated_at: str


def format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class ChatbotPromptStore:
    def __init__(
        self,
        *,
        blob_manager: BlobManager,
        container: str = CHATBOT_PROMPTS_CONTAINER,
        prompt_prefix: str = CHATBOT_PROMPTS_PREFIX,
    ):
        self.blob_manager = blob_manager
        self.container = container
        self.prompt_prefix = prompt_prefix.strip("/").strip()

    async def ensure_container_exists(self):
        container_client = self.blob_manager.blob_service_client.get_container_client(self.container)
        if not await container_client.exists():
            await container_client.create_container()
        return container_client

    def get_prompt_blob_name(self, chatbot_name: str) -> str:
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            raise ValueError("A valid chatbot name is required.")
        return f"{self.prompt_prefix}/{normalized_name}.json"

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

    def deserialize_prompt_override(self, chatbot_name: str, payload: dict | None) -> ChatbotPromptOverride | None:
        if payload is None:
            return None
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            return None
        prompt = payload.get("prompt")
        created_at = payload.get("createdAt")
        updated_at = payload.get("updatedAt")
        if not all(isinstance(value, str) and value for value in (prompt, created_at, updated_at)):
            logger.warning("Incomplete chatbot prompt payload for %s", normalized_name)
            return None
        payload_chatbot_name = payload.get("chatbotName")
        if isinstance(payload_chatbot_name, str) and normalize_chatbot_name(payload_chatbot_name) not in {
            None,
            normalized_name,
        }:
            logger.warning("Prompt blob chatbotName mismatch for %s", normalized_name)
            return None
        return ChatbotPromptOverride(
            chatbot_name=normalized_name,
            prompt=prompt,
            created_at=created_at,
            updated_at=updated_at,
        )

    async def load_prompt(self, chatbot_name: str) -> ChatbotPromptOverride | None:
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            return None
        payload = await self.load_json_blob(self.get_prompt_blob_name(normalized_name))
        return self.deserialize_prompt_override(normalized_name, payload)

    async def list_prompts(self) -> dict[str, ChatbotPromptOverride]:
        container_client = self.blob_manager.blob_service_client.get_container_client(self.container)
        if not await container_client.exists():
            return {}

        overrides: dict[str, ChatbotPromptOverride] = {}
        async for blob in container_client.list_blobs(name_starts_with=f"{self.prompt_prefix}/"):
            blob_name = getattr(blob, "name", None)
            if not blob_name:
                continue
            payload = await self.load_json_blob(blob_name)
            chatbot_name = blob_name.rsplit("/", 1)[-1].removesuffix(".json")
            prompt_override = self.deserialize_prompt_override(chatbot_name, payload)
            if prompt_override is not None:
                overrides[prompt_override.chatbot_name] = prompt_override
        return overrides

    async def save_prompt(
        self,
        chatbot_name: str,
        prompt: str,
        *,
        default_prompt: str | None = None,
    ) -> ChatbotPromptOverride | None:
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            raise ValueError("A valid chatbot name is required.")
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty.")
        if default_prompt is not None and prompt == default_prompt:
            await self.delete_prompt(normalized_name)
            return None

        existing_prompt = await self.load_prompt(normalized_name)
        now = format_utc(datetime.now(timezone.utc))
        prompt_override = ChatbotPromptOverride(
            chatbot_name=normalized_name,
            prompt=prompt,
            created_at=existing_prompt.created_at if existing_prompt is not None else now,
            updated_at=now,
        )
        await self.save_json_blob(
            self.get_prompt_blob_name(normalized_name),
            {
                "chatbotName": prompt_override.chatbot_name,
                "prompt": prompt_override.prompt,
                "createdAt": prompt_override.created_at,
                "updatedAt": prompt_override.updated_at,
            },
        )
        return prompt_override

    async def delete_prompt(self, chatbot_name: str) -> bool:
        normalized_name = normalize_chatbot_name(chatbot_name)
        if normalized_name is None:
            return False
        existing_prompt = await self.load_prompt(normalized_name)
        if existing_prompt is None:
            return False
        await self.delete_blob_if_exists(self.get_prompt_blob_name(normalized_name))
        return True
