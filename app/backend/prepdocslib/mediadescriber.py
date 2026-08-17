import base64
import logging
from abc import ABC
from typing import Optional

import aiohttp
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import get_bearer_token_provider
from openai import AsyncOpenAI, RateLimitError
from rich.progress import Progress
from tenacity import (
    AsyncRetrying,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
    wait_random_exponential,
)

logger = logging.getLogger("scripts")


class MediaDescriber(ABC):

    async def describe_image(self, image_bytes) -> str:
        raise NotImplementedError  # pragma: no cover


class ContentUnderstandingDescriber(MediaDescriber):
    CU_API_VERSION = "2024-12-01-preview"

    analyzer_schema = {
        "analyzerId": "image_analyzer",
        "name": "Image understanding",
        "description": "Extract detailed structured information from images extracted from documents.",
        "baseAnalyzerId": "prebuilt-image",
        "scenario": "image",
        "config": {"returnDetails": False},
        "fieldSchema": {
            "name": "ImageInformation",
            "descriptions": "Description of image.",
            "fields": {
                "Description": {
                    "type": "string",
                    "description": "Description of the image. If the image has a title, start with the title. Include a 2-sentence summary. If the image is a chart, diagram, or table, include the underlying data in an HTML table tag, with accurate numbers. If the image is a chart, describe any axis or legends. The only allowed HTML tags are the table/thead/tr/td/tbody tags.",
                },
            },
        },
    }

    def __init__(self, endpoint: str, credential: AsyncTokenCredential):
        self.endpoint = endpoint
        self.credential = credential

    async def poll_api(self, session, poll_url, headers):

        @retry(stop=stop_after_attempt(60), wait=wait_fixed(2), retry=retry_if_exception_type(ValueError))
        async def poll():
            async with session.get(poll_url, headers=headers) as response:
                response.raise_for_status()
                response_json = await response.json()
                if response_json["status"] == "Failed":
                    raise Exception("Failed")
                if response_json["status"] == "Running":
                    raise ValueError("Running")
                return response_json

        return await poll()

    async def create_analyzer(self):
        logger.info("Creating analyzer '%s'...", self.analyzer_schema["analyzerId"])

        token_provider = get_bearer_token_provider(self.credential, "https://cognitiveservices.azure.com/.default")
        token = await token_provider()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        params = {"api-version": self.CU_API_VERSION}
        analyzer_id = self.analyzer_schema["analyzerId"]
        cu_endpoint = f"{self.endpoint}/contentunderstanding/analyzers/{analyzer_id}"
        async with aiohttp.ClientSession() as session:
            async with session.put(
                url=cu_endpoint, params=params, headers=headers, json=self.analyzer_schema
            ) as response:
                if response.status == 409:
                    logger.info("Analyzer '%s' already exists.", analyzer_id)
                    return
                elif response.status != 201:
                    data = await response.text()
                    raise Exception("Error creating analyzer", data)
                else:
                    poll_url = response.headers.get("Operation-Location")

            with Progress() as progress:
                progress.add_task("Creating analyzer...", total=None, start=False)
                await self.poll_api(session, poll_url, headers)

    async def describe_image(self, image_bytes: bytes) -> str:
        async with aiohttp.ClientSession() as session:
            token = await self.credential.get_token("https://cognitiveservices.azure.com/.default")
            headers = {"Authorization": "Bearer " + token.token}
            params = {"api-version": self.CU_API_VERSION}
            analyzer_name = self.analyzer_schema["analyzerId"]
            async with session.post(
                url=f"{self.endpoint}/contentunderstanding/analyzers/{analyzer_name}:analyze",
                params=params,
                headers=headers,
                data=image_bytes,
            ) as response:
                response.raise_for_status()
                poll_url = response.headers["Operation-Location"]

                with Progress() as progress:
                    progress.add_task("Processing...", total=None, start=False)
                    results = await self.poll_api(session, poll_url, headers)

                fields = results["result"]["contents"][0]["fields"]
                return fields["Description"]["valueString"]


DEFAULT_IMAGE_DESCRIPTION_PROMPT = (
    "Describe image with no more than 5 sentences. Do not speculate about anything you don't know."
)

# Transcribe-first instruction used by feed ingestion (PublishOne ZIP packages), where an image is
# frequently a table, chart, or schedule that carries ALL of the document's data — a caption of such
# an image is worthless for retrieval, so the underlying values have to become searchable text.
FEED_IMAGE_DESCRIPTION_PROMPT = (
    "You are transcribing an image taken from a business document so that its content becomes searchable text.\n"
    "- If the image is a table, schedule, menu, chart, diagram, or form, reproduce ALL of its data as a Markdown "
    "table. Keep the exact row and column headers, every cell value, every number, and every code or footnote "
    "marker (for example allergen letters or calorie values) exactly as printed. Do not summarize, reorder, or "
    "drop rows.\n"
    "- Start with the image's own title or heading if it has one, followed by any date range, week number, or "
    "subtitle shown.\n"
    "- If the image is a photo, logo, screenshot, or illustration with no structured data, describe it in no more "
    "than 5 sentences instead.\n"
    "- Transcribe text in its original language. Do not translate.\n"
    "- Do not speculate about anything you cannot read. Never invent values."
)

# Reasoning models reject `max_tokens` and `seed`; they take `max_completion_tokens` instead.
REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def is_reasoning_model(model: Optional[str]) -> bool:
    normalized_model = (model or "").strip().lower()
    return any(normalized_model.startswith(prefix) for prefix in REASONING_MODEL_PREFIXES)


def image_media_type(image_bytes: bytes) -> str:
    """Sniff the media type from magic bytes, defaulting to PNG.

    Figure crops are PNG, but feed packages ship JPEG/GIF/WEBP too, and the data URI label has to
    match the payload.
    """
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"GIF8"):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


class MultimodalModelDescriber(MediaDescriber):
    def __init__(
        self,
        openai_client: AsyncOpenAI,
        model: str,
        deployment: Optional[str] = None,
        prompt: Optional[str] = None,
        max_tokens: int = 500,
    ):
        self.openai_client = openai_client
        self.model = model
        self.deployment = deployment
        self.prompt = prompt or DEFAULT_IMAGE_DESCRIPTION_PROMPT
        self.max_tokens = max_tokens

    def completion_kwargs(self) -> dict:
        """Token/determinism kwargs for the configured model.

        Reasoning models (gpt-5*, o1/o3/o4) reject `max_tokens` and `seed` outright, so a describer
        pointed at one would fail every call if we sent the classic parameters.
        """
        if is_reasoning_model(self.model):
            return {"max_completion_tokens": self.max_tokens}
        return {"max_tokens": self.max_tokens, "seed": 42}  # seed keeps responses consistent across runs

    async def describe_image(self, image_bytes: bytes) -> str:
        def before_retry_sleep(retry_state):
            logger.info("Rate limited on the OpenAI chat completions API, sleeping before retrying...")

        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        image_datauri = f"data:{image_media_type(image_bytes)};base64,{image_base64}"

        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(RateLimitError),
            wait=wait_random_exponential(min=15, max=60),
            stop=stop_after_attempt(15),
            before_sleep=before_retry_sleep,
        ):
            with attempt:
                response = await self.openai_client.chat.completions.create(
                    model=self.model if self.deployment is None else self.deployment,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful assistant that describes images from organizational documents.",
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "text": self.prompt,
                                    "type": "text",
                                },
                                {"image_url": {"url": image_datauri, "detail": "auto"}, "type": "image_url"},
                            ],
                        },
                    ],
                    **self.completion_kwargs(),
                )
        description = ""
        if response.choices and response.choices[0].message.content:
            description = response.choices[0].message.content.strip()
        return description
