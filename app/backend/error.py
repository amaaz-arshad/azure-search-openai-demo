import logging
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

from openai import APIError
from quart import has_request_context, jsonify, request

from approaches.chatbot_content_filter_registry import (
    SUPPORTED_CONTENT_FILTER_LANGUAGES,
    get_content_filter_message,
)
from approaches.chatbot_prompt_registry import normalize_chatbot_name

ERROR_MESSAGE = """The app encountered an error processing your request.
If you are an administrator of the app, check the application logs for a full traceback.
Error type: {error_type}
"""

ERROR_MESSAGE_LENGTH = """Your message exceeded the context length limit for this OpenAI model. Please shorten your message or change your settings to retrieve fewer search results."""


@dataclass(frozen=True)
class ErrorContext:
    chatbot_name: Optional[str] = None
    language: Optional[str] = None


def get_request_overrides(request_json: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(request_json, dict):
        return {}

    context = request_json.get("context")
    if not isinstance(context, dict):
        return {}

    overrides = context.get("overrides")
    if not isinstance(overrides, dict):
        return {}

    return overrides


def get_chatbot_name_from_referer(referer: Optional[str]) -> Optional[str]:
    if not referer:
        return None

    referer_path = urlparse(referer).path.strip("/")
    if not referer_path:
        return None

    return normalize_chatbot_name(referer_path.split("/", 1)[0])


def get_chatbot_name_from_overrides(overrides: dict[str, Any]) -> Optional[str]:
    include_category = overrides.get("include_category")
    if not isinstance(include_category, str):
        return None

    first_category = include_category.split(",", 1)[0].strip()
    return normalize_chatbot_name(first_category)


def get_request_error_context(request_json: Optional[dict[str, Any]] = None) -> ErrorContext:
    overrides = get_request_overrides(request_json)
    language = overrides.get("language") if isinstance(overrides.get("language"), str) else None
    chatbot_name = None

    if has_request_context():
        chatbot_name = normalize_chatbot_name(request.headers.get("X-Chatbot-Name"))
        if chatbot_name is None:
            chatbot_name = get_chatbot_name_from_referer(request.headers.get("Referer"))
        if language is None:
            language = request.accept_languages.best_match(list(SUPPORTED_CONTENT_FILTER_LANGUAGES))

    if chatbot_name is None:
        chatbot_name = get_chatbot_name_from_overrides(overrides)

    return ErrorContext(chatbot_name=chatbot_name, language=language)


def error_dict(error: Exception, error_context: Optional[ErrorContext] = None) -> dict:
    if isinstance(error, APIError) and error.code == "content_filter":
        resolved_error_context = error_context or ErrorContext()
        return {
            "error": get_content_filter_message(
                chatbot_name=resolved_error_context.chatbot_name,
                language=resolved_error_context.language,
            )
        }
    if isinstance(error, APIError) and error.code == "context_length_exceeded":
        return {"error": ERROR_MESSAGE_LENGTH}
    return {"error": ERROR_MESSAGE.format(error_type=type(error))}


def error_response(
    error: Exception,
    route: str,
    status_code: int = 500,
    error_context: Optional[ErrorContext] = None,
):
    logging.exception("Exception in %s: %s", route, error)
    if isinstance(error, APIError) and error.code == "content_filter":
        status_code = 400
    return jsonify(error_dict(error, error_context=error_context)), status_code
