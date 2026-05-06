import re
from collections.abc import AsyncGenerator, Awaitable
from dataclasses import asdict, dataclass
from typing import Any, Optional, cast

# --- Lemon-specific output sanitization -----------------------------------
# Lemon must never expose source labels, filenames, or structural identifiers.
# These patterns scrub anything the model might leak from the retrieval context.
_LEMON_SOURCE_LINE_RE = re.compile(
    r"""^\s*(?:>\s*)?[*_]{0,3}\s*
        (?:Source|Sources|Quelle|Quellen|
           Reference|References|Referenz|Referenzen|
           Citation|Citations|Zitat|Zitate|
           Quellenangabe|Quellenangaben|Fundstelle|Fundstellen)
        [*_]{0,3}\s*[:\-—–].*$""",
    re.IGNORECASE | re.VERBOSE,
)
_LEMON_INLINE_FILENAME_RE = re.compile(
    r"""[\[\(]\s*[^\[\]\(\)\s]+?\.(?:json|pdf|docx?|xlsx?|md|html?|txt|csv|pptx?)
        (?:[#?][^\[\]\(\)]*)?\s*[\]\)]""",
    re.IGNORECASE | re.VERBOSE,
)
_LEMON_INLINE_ID_RE = re.compile(r"[\[\(]\s*ID[-_]?\d+\s*[\]\)]", re.IGNORECASE)


def _is_lemon_chatbot(overrides: dict[str, Any]) -> bool:
    raw = overrides.get("include_category")
    if not isinstance(raw, str):
        return False
    primary = raw.split(",", 1)[0].strip().lower()
    return primary == "lemon"


def _sanitize_lemon_text(text: str) -> str:
    """Strip source labels, filename markers, and ID brackets from a complete text."""
    if not text:
        return text
    cleaned_lines = [line for line in text.split("\n") if not _LEMON_SOURCE_LINE_RE.match(line)]
    cleaned = "\n".join(cleaned_lines)
    cleaned = _LEMON_INLINE_FILENAME_RE.sub("", cleaned)
    cleaned = _LEMON_INLINE_ID_RE.sub("", cleaned)
    return cleaned.rstrip()


class _LemonStreamSanitizer:
    """Buffers streaming deltas line-by-line so source-style lines can be dropped before reaching the client."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: Optional[str]) -> str:
        if not chunk:
            return ""
        self._buffer += chunk
        out_parts: list[str] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if _LEMON_SOURCE_LINE_RE.match(line):
                continue
            line = _LEMON_INLINE_FILENAME_RE.sub("", line)
            line = _LEMON_INLINE_ID_RE.sub("", line)
            out_parts.append(line + "\n")
        return "".join(out_parts)

    def flush(self) -> str:
        tail = self._buffer
        self._buffer = ""
        if _LEMON_SOURCE_LINE_RE.match(tail):
            return ""
        tail = _LEMON_INLINE_FILENAME_RE.sub("", tail)
        tail = _LEMON_INLINE_ID_RE.sub("", tail)
        return tail
# ---------------------------------------------------------------------------

from azure.search.documents.aio import SearchClient
from azure.search.documents.knowledgebases.aio import KnowledgeBaseRetrievalClient
from azure.search.documents.models import VectorQuery
from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionMessageParam,
)
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage

from approaches.approach import (
    Approach,
    DataPoints,
    ExtraInfo,
    ThoughtStep,
)
from approaches.chatbot_config_registry import get_chatbot_citation_target
from approaches.promptmanager import PromptManager
from prepdocslib.blobmanager import AdlsBlobManager, BlobManager
from prepdocslib.embeddings import ImageEmbeddings


@dataclass(frozen=True)
class LlmWikiPage:
    blob_path: str
    relative_path: str
    citation: str
    title: str
    content: str


class ChatReadRetrieveReadApproach(Approach):
    """
    A multi-step approach that first uses OpenAI to turn the user's question into a search query,
    then uses Azure AI Search to retrieve relevant documents, and then sends the conversation history,
    original user question, and search results to OpenAI to generate a response.
    """

    NO_RESPONSE = Approach.QUERY_REWRITE_NO_RESPONSE
    LLM_WIKI_BLOB_ROOT = "__llm_wiki__"
    LLM_WIKI_INDEX_FILE = "index.md"
    LLM_WIKI_LOG_FILE = "log.md"
    LLM_WIKI_MAX_CONTEXT_CHARS = 60000
    LLM_WIKI_MAX_PAGES = 16

    def __init__(
        self,
        *,
        search_client: SearchClient,
        search_index_name: str,
        knowledgebase_model: Optional[str],
        knowledgebase_deployment: Optional[str],
        knowledgebase_client: Optional[KnowledgeBaseRetrievalClient],
        knowledgebase_client_with_web: Optional[KnowledgeBaseRetrievalClient] = None,
        knowledgebase_client_with_sharepoint: Optional[KnowledgeBaseRetrievalClient] = None,
        knowledgebase_client_with_web_and_sharepoint: Optional[KnowledgeBaseRetrievalClient] = None,
        openai_client: AsyncOpenAI,
        chatgpt_model: str,
        chatgpt_deployment: Optional[str],  # Not needed for non-Azure OpenAI
        embedding_deployment: Optional[str],  # Not needed for non-Azure OpenAI or for retrieval_mode="text"
        embedding_model: str,
        embedding_dimensions: int,
        embedding_field: str,
        sourcepage_field: str,
        content_field: str,
        query_language: str,
        query_speller: str,
        prompt_manager: PromptManager,
        reasoning_effort: Optional[str] = None,
        multimodal_enabled: bool = False,
        image_embeddings_client: Optional[ImageEmbeddings] = None,
        global_blob_manager: Optional[BlobManager] = None,
        user_blob_manager: Optional[AdlsBlobManager] = None,
        use_web_source: bool = False,
        use_sharepoint_source: bool = False,
        retrieval_reasoning_effort: Optional[str] = None,
        chat_model_deployments: Optional[dict[str, Optional[str]]] = None,
    ):
        self.search_client = search_client
        self.search_index_name = search_index_name
        self.knowledgebase_model = knowledgebase_model
        self.knowledgebase_deployment = knowledgebase_deployment
        self.knowledgebase_client = knowledgebase_client
        self.knowledgebase_client_with_web = knowledgebase_client_with_web
        self.knowledgebase_client_with_sharepoint = knowledgebase_client_with_sharepoint
        self.knowledgebase_client_with_web_and_sharepoint = knowledgebase_client_with_web_and_sharepoint
        self.openai_client = openai_client
        self.chatgpt_model = chatgpt_model
        self.chatgpt_deployment = chatgpt_deployment
        self.embedding_deployment = embedding_deployment
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.embedding_field = embedding_field
        self.sourcepage_field = sourcepage_field
        self.content_field = content_field
        self.query_language = query_language
        self.query_speller = query_speller
        self.prompt_manager = prompt_manager
        self.query_rewrite_tools = self.prompt_manager.load_tools("chat_query_rewrite_tools.json")
        self.reasoning_effort = reasoning_effort
        self.include_token_usage = True
        self.multimodal_enabled = multimodal_enabled
        self.image_embeddings_client = image_embeddings_client
        self.global_blob_manager = global_blob_manager
        self.user_blob_manager = user_blob_manager
        # Track whether web source retrieval is enabled for this deployment; overrides may only disable it.
        self.web_source_enabled = use_web_source
        self.use_sharepoint_source = use_sharepoint_source
        self.retrieval_reasoning_effort = retrieval_reasoning_effort
        self.chat_model_deployments = chat_model_deployments or {}

    def extract_followup_questions(self, content: Optional[str]):
        if content is None:
            return content, []
        return content.split("<<")[0], re.findall(r"<<([^>>]+)>>", content)

    def get_search_query(self, chat_completion: ChatCompletion, default_query: str) -> str:
        """Read the optimized search query from a chat completion tool call."""
        try:
            return self.extract_rewritten_query(chat_completion, default_query, no_response_token=self.NO_RESPONSE)
        except Exception:
            return default_query

    @staticmethod
    def get_document_citation_target(include_category: Any) -> str:
        if not isinstance(include_category, str):
            return "sourcepage"
        primary_category = include_category.split(",", 1)[0].strip().lower()
        return get_chatbot_citation_target(primary_category)

    @staticmethod
    def normalize_llm_wiki_source_chatbot(source_chatbot: str) -> str:
        normalized_source = source_chatbot.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", normalized_source):
            raise ValueError("Invalid LLM Wiki source chatbot.")
        return normalized_source

    @classmethod
    def get_llm_wiki_blob_prefix(cls, source_chatbot: str) -> str:
        normalized_source = cls.normalize_llm_wiki_source_chatbot(source_chatbot)
        return f"{cls.LLM_WIKI_BLOB_ROOT}/{normalized_source}/wiki"

    @staticmethod
    def normalize_llm_wiki_relative_path(relative_path: str) -> str:
        path_parts = [part for part in relative_path.replace("\\", "/").split("/") if part and part != "."]
        if not path_parts or any(part == ".." for part in path_parts):
            raise ValueError("Invalid LLM Wiki page path.")
        normalized_path = "/".join(path_parts)
        if not normalized_path.lower().endswith(".md"):
            normalized_path = f"{normalized_path}.md"
        return normalized_path

    @classmethod
    def get_llm_wiki_blob_path(cls, source_chatbot: str, relative_path: str) -> str:
        return f"{cls.get_llm_wiki_blob_prefix(source_chatbot)}/{cls.normalize_llm_wiki_relative_path(relative_path)}"

    @classmethod
    def get_llm_wiki_relative_path(cls, source_chatbot: str, blob_path: str) -> str:
        prefix = f"{cls.get_llm_wiki_blob_prefix(source_chatbot)}/"
        if not blob_path.startswith(prefix):
            return blob_path
        return blob_path[len(prefix) :]

    @staticmethod
    def get_markdown_title(markdown: str, fallback: str) -> str:
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or fallback
        return fallback

    @staticmethod
    def extract_llm_wiki_index_paths(index_content: str) -> list[str]:
        candidate_paths: list[str] = []

        for match in re.finditer(r"\[\[([^\]\n]+)\]\]", index_content):
            target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
            if target:
                candidate_paths.append(target)

        for match in re.finditer(r"\[[^\]\n]+\]\(([^)\n]+)\)", index_content):
            target = match.group(1).split("#", 1)[0].strip()
            if target and not re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                candidate_paths.append(target)

        normalized_paths: list[str] = []
        for path in candidate_paths:
            try:
                normalized_path = ChatReadRetrieveReadApproach.normalize_llm_wiki_relative_path(path)
            except ValueError:
                continue
            if normalized_path not in normalized_paths:
                normalized_paths.append(normalized_path)
        return normalized_paths

    @staticmethod
    def score_llm_wiki_page(query: str, page: LlmWikiPage) -> int:
        query_terms = set(re.findall(r"[a-z0-9]{3,}", query.lower()))
        if not query_terms:
            return 0
        title = page.title.lower()
        path = page.relative_path.lower()
        content = page.content.lower()
        score = 0
        for term in query_terms:
            if term in title:
                score += 10
            if term in path:
                score += 4
            if term in content:
                score += content.count(term)
        return score

    @classmethod
    def select_llm_wiki_pages(cls, pages: list[LlmWikiPage], query: str) -> list[LlmWikiPage]:
        index_pages = [page for page in pages if page.relative_path.lower() == cls.LLM_WIKI_INDEX_FILE]
        query_pages = [page for page in pages if page.relative_path.lower() != cls.LLM_WIKI_LOG_FILE]
        index_page = index_pages[0] if index_pages else None

        selected_paths: list[str] = []
        if index_page:
            selected_paths.append(index_page.relative_path)
            selected_paths.extend(cls.extract_llm_wiki_index_paths(index_page.content))

        if len(query_pages) <= cls.LLM_WIKI_MAX_PAGES:
            selected_paths.extend(page.relative_path for page in query_pages)
        else:
            ranked_pages = sorted(
                (page for page in query_pages if page.relative_path.lower() != cls.LLM_WIKI_INDEX_FILE),
                key=lambda page: cls.score_llm_wiki_page(query, page),
                reverse=True,
            )
            selected_paths.extend(page.relative_path for page in ranked_pages[: cls.LLM_WIKI_MAX_PAGES])

        pages_by_path = {page.relative_path: page for page in pages}
        selected_pages: list[LlmWikiPage] = []
        used_chars = 0
        for path in dict.fromkeys(selected_paths):
            page = pages_by_path.get(path)
            if page is None:
                continue
            page_size = len(page.content)
            if selected_pages and used_chars + page_size > cls.LLM_WIKI_MAX_CONTEXT_CHARS:
                continue
            selected_pages.append(page)
            used_chars += page_size
            if len(selected_pages) >= cls.LLM_WIKI_MAX_PAGES:
                break
        return selected_pages

    async def load_llm_wiki_pages(self, source_chatbot: str) -> list[LlmWikiPage]:
        if self.global_blob_manager is None:
            return []

        blob_prefix = self.get_llm_wiki_blob_prefix(source_chatbot)
        blob_entries = await self.global_blob_manager.list_blobs(f"{blob_prefix}/")
        blob_paths = sorted(
            entry.name
            for entry in blob_entries
            if getattr(entry, "name", "").lower().endswith(".md")
        )
        pages: list[LlmWikiPage] = []
        for blob_path in blob_paths:
            download_result = await self.global_blob_manager.download_blob(blob_path)
            if download_result is None:
                continue
            content_bytes, _properties = download_result
            content = content_bytes.decode("utf-8-sig", errors="replace").strip()
            if not content:
                continue
            relative_path = self.get_llm_wiki_relative_path(source_chatbot, blob_path)
            pages.append(
                LlmWikiPage(
                    blob_path=blob_path,
                    relative_path=relative_path,
                    citation=blob_path,
                    title=self.get_markdown_title(content, relative_path),
                    content=content,
                )
            )
        return pages

    async def answer_from_llm_wiki(
        self,
        *,
        source_chatbot: str,
        user_query: str,
        selected_pages: list[LlmWikiPage],
        overrides: dict[str, Any],
        chatgpt_model: str,
        chatgpt_deployment: Optional[str],
    ) -> tuple[str, list[ChatCompletionMessageParam], ChatCompletion]:
        messages = cast(
            list[ChatCompletionMessageParam],
            [
                self.prompt_manager.build_system_prompt(
                    "llm_wiki_answer.system.jinja2",
                    {"source_chatbot": source_chatbot},
                ),
                self.prompt_manager.build_user_prompt(
                    "llm_wiki_answer.user.jinja2",
                    {
                        "user_query": user_query,
                        "wiki_pages": selected_pages,
                    },
                ),
            ],
        )
        completion = cast(
            ChatCompletion,
            await self.create_chat_completion(
                chatgpt_deployment,
                chatgpt_model,
                messages,
                overrides,
                response_token_limit=self.get_response_token_limit(chatgpt_model, 1600),
                temperature=0.0,
            ),
        )
        content = completion.choices[0].message.content or ""
        return str(content.strip()), messages, completion

    async def run_without_streaming(
        self,
        messages: list[ChatCompletionMessageParam],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        session_state: Any = None,
    ) -> dict[str, Any]:
        extra_info, chat_coroutine = await self.run_until_final_call(
            messages, overrides, auth_claims, should_stream=False
        )
        chat_completion_response: ChatCompletion = await cast(Awaitable[ChatCompletion], chat_coroutine)
        content = chat_completion_response.choices[0].message.content
        role = chat_completion_response.choices[0].message.role
        if overrides.get("suggest_followup_questions"):
            content, followup_questions = self.extract_followup_questions(content)
            extra_info.followup_questions = followup_questions
        if _is_lemon_chatbot(overrides) and isinstance(content, str):
            content = _sanitize_lemon_text(content)
        # Assume last thought is for generating answer
        # TODO: Update for agentic? This isn't still true?
        if self.include_token_usage and extra_info.thoughts and chat_completion_response.usage:
            extra_info.thoughts[-1].update_token_usage(chat_completion_response.usage)
        chat_app_response = {
            "message": {"content": content, "role": role},
            "context": {
                "thoughts": extra_info.thoughts,
                "data_points": {
                    key: value for key, value in asdict(extra_info.data_points).items() if value is not None
                },
                "followup_questions": extra_info.followup_questions,
            },
            "session_state": session_state,
        }
        return chat_app_response

    async def run_with_streaming(
        self,
        messages: list[ChatCompletionMessageParam],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        session_state: Any = None,
    ) -> AsyncGenerator[dict, None]:
        extra_info, chat_coroutine = await self.run_until_final_call(
            messages, overrides, auth_claims, should_stream=True
        )
        yield {"delta": {"role": "assistant"}, "context": extra_info, "session_state": session_state}

        followup_questions_started = False
        followup_content = ""
        chat_result = await chat_coroutine
        is_lemon = _is_lemon_chatbot(overrides)
        lemon_stream_sanitizer = _LemonStreamSanitizer() if is_lemon else None

        if isinstance(chat_result, ChatCompletion):
            message = chat_result.choices[0].message
            content = message.content or ""
            role = message.role or "assistant"

            followup_questions: list[str] = []
            if overrides.get("suggest_followup_questions"):
                content, followup_questions = self.extract_followup_questions(content)
                extra_info.followup_questions = followup_questions

            if is_lemon:
                content = _sanitize_lemon_text(content)

            if self.include_token_usage and extra_info.thoughts and chat_result.usage:
                extra_info.thoughts[-1].update_token_usage(chat_result.usage)

            delta_payload: dict[str, Any] = {"role": role}
            if content:
                delta_payload["content"] = content
            yield {"delta": delta_payload}

            yield {"delta": {"role": "assistant"}, "context": extra_info, "session_state": session_state}

            if followup_questions:
                yield {
                    "delta": {"role": "assistant"},
                    "context": {"context": extra_info, "followup_questions": followup_questions},
                }
            return

        chat_result = cast(AsyncStream[ChatCompletionChunk], chat_result)

        async for event_chunk in chat_result:
            # "2023-07-01-preview" API version has a bug where first response has empty choices
            event = event_chunk.model_dump()  # Convert pydantic model to dict
            if event["choices"]:
                # No usage during streaming
                completion = {
                    "delta": {
                        "content": event["choices"][0]["delta"].get("content"),
                        "role": event["choices"][0]["delta"]["role"],
                    }
                }
                # if event contains << and not >>, it is start of follow-up question, truncate
                delta_content_raw = completion["delta"].get("content")
                delta_content: str = (
                    delta_content_raw or ""
                )  # content may either not exist in delta, or explicitly be None
                if overrides.get("suggest_followup_questions") and "<<" in delta_content:
                    followup_questions_started = True
                    earlier_content = delta_content[: delta_content.index("<<")]
                    if earlier_content:
                        if lemon_stream_sanitizer is not None:
                            earlier_content = lemon_stream_sanitizer.feed(earlier_content)
                            if not earlier_content:
                                # everything in this chunk was buffered; nothing to emit yet
                                pass
                        if earlier_content:
                            completion["delta"]["content"] = earlier_content
                            yield completion
                    followup_content += delta_content[delta_content.index("<<") :]
                elif followup_questions_started:
                    followup_content += delta_content
                else:
                    if lemon_stream_sanitizer is not None:
                        sanitized = lemon_stream_sanitizer.feed(delta_content)
                        if not sanitized:
                            continue
                        completion["delta"]["content"] = sanitized
                    yield completion
            else:
                # Final chunk at end of streaming should contain usage
                # https://cookbook.openai.com/examples/how_to_stream_completions#4-how-to-get-token-usage-data-for-streamed-chat-completion-response
                if event_chunk.usage and extra_info.thoughts and self.include_token_usage:
                    extra_info.thoughts[-1].update_token_usage(event_chunk.usage)
                    yield {"delta": {"role": "assistant"}, "context": extra_info, "session_state": session_state}

        if lemon_stream_sanitizer is not None:
            tail = lemon_stream_sanitizer.flush()
            if tail:
                yield {"delta": {"role": "assistant", "content": tail}}

        if followup_content:
            _, followup_questions = self.extract_followup_questions(followup_content)
            yield {
                "delta": {"role": "assistant"},
                "context": {"context": extra_info, "followup_questions": followup_questions},
            }

    async def run(
        self,
        messages: list[ChatCompletionMessageParam],
        session_state: Any = None,
        context: dict[str, Any] = {},
    ) -> dict[str, Any]:
        overrides = context.get("overrides", {})
        auth_claims = context.get("auth_claims", {})
        return await self.run_without_streaming(messages, overrides, auth_claims, session_state)

    async def run_stream(
        self,
        messages: list[ChatCompletionMessageParam],
        session_state: Any = None,
        context: dict[str, Any] = {},
    ) -> AsyncGenerator[dict[str, Any], None]:
        overrides = context.get("overrides", {})
        auth_claims = context.get("auth_claims", {})
        return self.run_with_streaming(messages, overrides, auth_claims, session_state)

    async def run_until_final_call(
        self,
        messages: list[ChatCompletionMessageParam],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        should_stream: bool = False,
    ) -> tuple[ExtraInfo, Awaitable[ChatCompletion] | Awaitable[AsyncStream[ChatCompletionChunk]]]:
        use_agentic_knowledgebase = True if overrides.get("use_agentic_knowledgebase") else False
        use_llm_wiki = bool(overrides.get("use_llm_wiki") and isinstance(overrides.get("source_chatbot"), str))
        original_user_query = messages[-1]["content"]
        effective_chatgpt_model, effective_chatgpt_deployment = self.resolve_chat_model_and_deployment(
            overrides, self.chatgpt_model, self.chatgpt_deployment
        )

        reasoning_model_support = self.GPT_REASONING_MODELS.get(effective_chatgpt_model)
        if reasoning_model_support and (not reasoning_model_support.streaming and should_stream):
            raise Exception(
                f"{effective_chatgpt_model} does not support streaming. Please use a different model or disable streaming."
            )
        if use_llm_wiki:
            extra_info = await self.run_llm_wiki_approach(messages, overrides, auth_claims)
        elif use_agentic_knowledgebase:
            if should_stream and overrides.get("use_web_source"):
                raise Exception(
                    "Streaming is not supported with agentic retrieval when web source is enabled. Please disable streaming or web source."
                )
            extra_info = await self.run_agentic_retrieval_approach(messages, overrides, auth_claims)
        else:
            extra_info = await self.run_search_approach(messages, overrides, auth_claims)

        if extra_info.answer:
            # Some approaches, such as agentic web retrieval and pure LLM Wiki, already provide the final answer.
            async def return_answer() -> ChatCompletion:
                return ChatCompletion(
                    id="no-final-call",
                    object="chat.completion",
                    created=0,
                    model=effective_chatgpt_model,
                    choices=[
                        Choice(
                            message=ChatCompletionMessage(
                                role="assistant",
                                content=extra_info.answer,
                            ),
                            finish_reason="stop",
                            index=0,
                        )
                    ],
                )

            return (extra_info, return_answer())

        chatbot_name_override = overrides.get("include_category")
        if isinstance(chatbot_name_override, str) and "," in chatbot_name_override:
            chatbot_name_override = chatbot_name_override.split(",", 1)[0].strip()
        user_template_path = (
            "chat_answer.user.lemon.jinja2" if _is_lemon_chatbot(overrides) else "chat_answer.user.jinja2"
        )
        messages = self.prompt_manager.build_conversation(
            system_template_path="chat_answer.system.jinja2",
            system_template_variables=self.get_system_prompt_variables(
                overrides.get("prompt_template"),
                chatbot_name_override if isinstance(chatbot_name_override, str) else None,
                saved_prompt=(
                    overrides.get("__saved_prompt_template")
                    if isinstance(overrides.get("__saved_prompt_template"), str)
                    else None
                ),
                citations=extra_info.data_points.citations,
                language=overrides.get("language"),
            )
            | {
                "include_follow_up_questions": bool(overrides.get("suggest_followup_questions")),
                "image_sources": extra_info.data_points.images,
                "citations": extra_info.data_points.citations,
            },
            user_template_path=user_template_path,
            user_template_variables={
                "user_query": original_user_query,
                "text_sources": extra_info.data_points.text,
            },
            user_image_sources=extra_info.data_points.images,
            past_messages=messages[:-1],
        )

        chat_coroutine = cast(
            Awaitable[ChatCompletion] | Awaitable[AsyncStream[ChatCompletionChunk]],
            self.create_chat_completion(
                effective_chatgpt_deployment,
                effective_chatgpt_model,
                messages,
                overrides,
                self.get_response_token_limit(effective_chatgpt_model, 1024),
                should_stream,
            ),
        )
        extra_info.thoughts.append(
            self.format_thought_step_for_chatcompletion(
                title="Prompt to generate answer",
                messages=messages,
                overrides=overrides,
                model=effective_chatgpt_model,
                deployment=effective_chatgpt_deployment,
                usage=None,
            )
        )
        return (extra_info, chat_coroutine)

    async def run_search_approach(
        self, messages: list[ChatCompletionMessageParam], overrides: dict[str, Any], auth_claims: dict[str, Any]
    ):
        use_text_search = overrides.get("retrieval_mode") in ["text", "hybrid", None]
        use_vector_search = overrides.get("retrieval_mode") in ["vectors", "hybrid", None]
        use_semantic_ranker = True if overrides.get("semantic_ranker") else False
        use_semantic_captions = True if overrides.get("semantic_captions") else False
        use_query_rewriting = True if overrides.get("query_rewriting") else False
        top = overrides.get("top", 3)
        minimum_search_score = overrides.get("minimum_search_score", 0.0)
        minimum_reranker_score = overrides.get("minimum_reranker_score", 0.0)
        search_index_filter = self.build_filter(overrides)
        access_token = auth_claims.get("access_token")
        send_text_sources = overrides.get("send_text_sources", True)
        send_image_sources = overrides.get("send_image_sources", self.multimodal_enabled) and self.multimodal_enabled
        search_text_embeddings = overrides.get("search_text_embeddings", True)
        search_image_embeddings = (
            overrides.get("search_image_embeddings", self.multimodal_enabled) and self.multimodal_enabled
        )
        document_citation_target = self.get_document_citation_target(overrides.get("include_category"))

        original_user_query = messages[-1]["content"]
        if not isinstance(original_user_query, str):
            raise ValueError("The most recent message content must be a string.")
        effective_chatgpt_model, effective_chatgpt_deployment = self.resolve_chat_model_and_deployment(
            overrides, self.chatgpt_model, self.chatgpt_deployment
        )

        # STEP 1: Generate an optimized keyword search query based on the chat history and the last question

        rewrite_result = await self.rewrite_query(
            prompt_template="query_rewrite.system.jinja2",
            prompt_variables={
                "user_query": original_user_query,
                "past_messages": messages[:-1],
            },
            overrides=overrides,
            chatgpt_model=effective_chatgpt_model,
            chatgpt_deployment=effective_chatgpt_deployment,
            user_query=original_user_query,
            response_token_limit=self.get_response_token_limit(
                effective_chatgpt_model, 100
            ),  # Setting too low risks malformed JSON, setting too high may affect performance
            tools=self.query_rewrite_tools,
            temperature=0.0,  # Minimize creativity for search query generation
            no_response_token=self.NO_RESPONSE,
        )

        query_text = rewrite_result.query

        # STEP 2: Retrieve relevant documents from the search index with the GPT optimized query

        vectors: list[VectorQuery] = []
        if use_vector_search:
            if search_text_embeddings:
                vectors.append(await self.compute_text_embedding(query_text))
            if search_image_embeddings:
                vectors.append(await self.compute_multimodal_embedding(query_text))

        results = await self.search(
            top,
            query_text,
            search_index_filter,
            vectors,
            use_text_search,
            use_vector_search,
            use_semantic_ranker,
            use_semantic_captions,
            minimum_search_score,
            minimum_reranker_score,
            use_query_rewriting,
            access_token,
        )

        # STEP 3: Generate a contextual and content specific answer using the search results and chat history
        data_points = await self.get_sources_content(
            results,
            use_semantic_captions,
            include_text_sources=send_text_sources,
            download_image_sources=send_image_sources,
            user_oid=auth_claims.get("oid"),
            document_citation_target=document_citation_target,
        )
        extra_info = ExtraInfo(
            data_points,
            thoughts=[
                self.format_thought_step_for_chatcompletion(
                    title="Prompt to generate search query",
                    messages=rewrite_result.messages,
                    overrides=overrides,
                    model=effective_chatgpt_model,
                    deployment=effective_chatgpt_deployment,
                    usage=rewrite_result.completion.usage,
                    reasoning_effort=rewrite_result.reasoning_effort,
                ),
                ThoughtStep(
                    "Search using generated search query",
                    query_text,
                    {
                        "use_semantic_captions": use_semantic_captions,
                        "use_semantic_ranker": use_semantic_ranker,
                        "use_query_rewriting": use_query_rewriting,
                        "top": top,
                        "filter": search_index_filter,
                        "use_vector_search": use_vector_search,
                        "use_text_search": use_text_search,
                        "search_text_embeddings": search_text_embeddings,
                        "search_image_embeddings": search_image_embeddings,
                    },
                ),
                ThoughtStep(
                    "Search results",
                    [result.serialize_for_results() for result in results],
                ),
            ],
        )
        return extra_info

    async def run_llm_wiki_approach(
        self,
        messages: list[ChatCompletionMessageParam],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
    ) -> ExtraInfo:
        source_chatbot = overrides.get("source_chatbot")
        if not isinstance(source_chatbot, str) or not source_chatbot.strip():
            return await self.run_search_approach(messages, overrides, auth_claims)

        original_user_query = messages[-1]["content"]
        if not isinstance(original_user_query, str):
            raise ValueError("The most recent message content must be a string.")
        effective_chatgpt_model, effective_chatgpt_deployment = self.resolve_chat_model_and_deployment(
            overrides, self.chatgpt_model, self.chatgpt_deployment
        )

        blob_prefix = self.get_llm_wiki_blob_prefix(source_chatbot)
        pages = await self.load_llm_wiki_pages(source_chatbot)
        selected_pages = self.select_llm_wiki_pages(pages, original_user_query)
        wiki_sources = [
            f"LLM Wiki - {page.title} ({page.citation}):\n{page.content}" for page in selected_pages
        ]
        data_points = DataPoints(
            text=wiki_sources,
            images=[],
            citations=[page.citation for page in selected_pages],
        )
        thoughts = [
            ThoughtStep(
                "Load LLM Wiki from blob storage",
                {
                    "source_chatbot": source_chatbot,
                    "blob_prefix": blob_prefix,
                    "pages_found": len(pages),
                    "pages_loaded": [page.citation for page in selected_pages],
                },
            )
        ]

        if not selected_pages:
            return ExtraInfo(
                data_points,
                thoughts=thoughts,
                answer=(
                    f"I do not have an LLM Wiki for '{source_chatbot}' yet. "
                    f"Upload Markdown pages under '{blob_prefix}/' and try again."
                ),
            )

        answer, wiki_answer_messages, wiki_answer_completion = await self.answer_from_llm_wiki(
            source_chatbot=source_chatbot,
            user_query=original_user_query,
            selected_pages=selected_pages,
            overrides=overrides,
            chatgpt_model=effective_chatgpt_model,
            chatgpt_deployment=effective_chatgpt_deployment,
        )
        if not answer:
            answer = "The selected LLM Wiki did not produce an answer for this question."
        thoughts.append(
            self.format_thought_step_for_chatcompletion(
                title="Prompt to answer from LLM Wiki",
                messages=wiki_answer_messages,
                overrides=overrides,
                model=effective_chatgpt_model,
                deployment=effective_chatgpt_deployment,
                usage=wiki_answer_completion.usage,
            )
        )

        return ExtraInfo(
            data_points,
            thoughts=thoughts,
            answer=answer,
        )

    async def run_agentic_retrieval_approach(
        self,
        messages: list[ChatCompletionMessageParam],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
    ):
        search_index_filter = self.build_filter(overrides)
        access_token = auth_claims.get("access_token")
        minimum_reranker_score = overrides.get("minimum_reranker_score", 0)
        send_text_sources = overrides.get("send_text_sources", True)
        send_image_sources = overrides.get("send_image_sources", self.multimodal_enabled) and self.multimodal_enabled
        retrieval_reasoning_effort = overrides.get("retrieval_reasoning_effort", self.retrieval_reasoning_effort)
        document_citation_target = self.get_document_citation_target(overrides.get("include_category"))
        # Overrides can only disable web source support configured at construction time.
        use_web_source = self.web_source_enabled
        override_use_web_source = overrides.get("use_web_source")
        if isinstance(override_use_web_source, bool):
            use_web_source = use_web_source and override_use_web_source
        # Overrides can only disable sharepoint source support configured at construction time.
        use_sharepoint_source = self.use_sharepoint_source
        override_use_sharepoint_source = overrides.get("use_sharepoint_source")
        if isinstance(override_use_sharepoint_source, bool):
            use_sharepoint_source = use_sharepoint_source and override_use_sharepoint_source
        if use_web_source and retrieval_reasoning_effort == "minimal":
            raise Exception("Web source cannot be used with minimal retrieval reasoning effort.")

        selected_client, effective_web_source, effective_sharepoint_source = self._select_knowledgebase_client(
            use_web_source,
            use_sharepoint_source,
        )

        agentic_results = await self.run_agentic_retrieval(
            messages=messages,
            knowledgebase_client=selected_client,
            search_index_name=self.search_index_name,
            overrides=overrides,
            filter_add_on=search_index_filter,
            minimum_reranker_score=minimum_reranker_score,
            access_token=access_token,
            use_web_source=effective_web_source,
            use_sharepoint_source=effective_sharepoint_source,
            retrieval_reasoning_effort=retrieval_reasoning_effort,
            document_citation_target=document_citation_target,
        )

        data_points = await self.get_sources_content(
            agentic_results.documents,
            use_semantic_captions=False,
            include_text_sources=send_text_sources,
            download_image_sources=send_image_sources,
            user_oid=auth_claims.get("oid"),
            web_results=agentic_results.web_results,
            sharepoint_results=agentic_results.sharepoint_results,
            document_citation_target=document_citation_target,
        )

        return ExtraInfo(
            data_points,
            thoughts=agentic_results.thoughts,
            answer=agentic_results.answer,
        )

    def _select_knowledgebase_client(
        self,
        use_web_source: bool,
        use_sharepoint_source: bool,
    ) -> tuple[KnowledgeBaseRetrievalClient, bool, bool]:
        if use_web_source and use_sharepoint_source:
            if self.knowledgebase_client_with_web_and_sharepoint:
                return self.knowledgebase_client_with_web_and_sharepoint, True, True
            if self.knowledgebase_client_with_web:
                return self.knowledgebase_client_with_web, True, False
            if self.knowledgebase_client_with_sharepoint:
                return self.knowledgebase_client_with_sharepoint, False, True

        if use_web_source and self.knowledgebase_client_with_web:
            return self.knowledgebase_client_with_web, True, False

        if use_sharepoint_source and self.knowledgebase_client_with_sharepoint:
            return self.knowledgebase_client_with_sharepoint, False, True

        if self.knowledgebase_client:
            return self.knowledgebase_client, False, False
        raise ValueError("Agentic retrieval requested but no knowledge base is configured")
