import logging
import re
from functools import lru_cache
from importlib import import_module
from typing import Optional

from approaches.chatbot_prompt_registry import normalize_chatbot_name

logger = logging.getLogger(__name__)

DEFAULT_CONTENT_FILTER_MESSAGES = {
    "da": "Din besked indeholder indhold, der blev markeret af OpenAI's indholdsfilter.",
    "de": "Deine Nachricht enthält Inhalte, die vom OpenAI-Inhaltsfilter markiert wurden.",
    "en": "Your message contains content that was flagged by the OpenAI content filter.",
    "es": "Tu mensaje contiene contenido que fue marcado por el filtro de contenido de OpenAI.",
    "fr": "Votre message contient du contenu signalé par le filtre de contenu d'OpenAI.",
    "it": "Il tuo messaggio contiene contenuti segnalati dal filtro dei contenuti di OpenAI.",
    "ja": "メッセージに、OpenAI のコンテンツフィルターでフラグされた内容が含まれています。",
    "nl": "Je bericht bevat inhoud die door het OpenAI-inhoudsfilter is gemarkeerd.",
    "pl": "Twoja wiadomość zawiera treść oznaczoną przez filtr treści OpenAI.",
    "pt-BR": "Sua mensagem contém conteúdo sinalizado pelo filtro de conteúdo da OpenAI.",
    "tr": "Mesajınız, OpenAI içerik filtresi tarafından işaretlenen içerik içeriyor.",
}

SUPPORTED_CONTENT_FILTER_LANGUAGES = tuple(DEFAULT_CONTENT_FILTER_MESSAGES.keys())

LANGUAGE_ALIASES = {
    "nlbe": "nl",
    "nl-be": "nl",
    "nl_be": "nl",
    "pt": "pt-BR",
    "ptbr": "pt-BR",
    "pt-br": "pt-BR",
    "pt_br": "pt-BR",
}


def normalize_content_filter_language(language: Optional[str]) -> Optional[str]:
    if not language:
        return None

    stripped_language = language.strip()
    if not stripped_language:
        return None

    lowered_language = stripped_language.lower()
    if lowered_language in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[lowered_language]

    collapsed_language = re.sub(r"[^a-z]", "", lowered_language)
    if collapsed_language in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[collapsed_language]

    base_language = stripped_language.replace("_", "-").split("-", 1)[0].lower()
    if base_language in DEFAULT_CONTENT_FILTER_MESSAGES:
        return base_language

    return None


def normalize_content_filter_messages(messages: object) -> dict[str, str]:
    if not isinstance(messages, dict):
        return {}

    normalized_messages: dict[str, str] = {}
    for language, message in messages.items():
        if not isinstance(language, str) or not isinstance(message, str) or not message.strip():
            continue
        normalized_language = normalize_content_filter_language(language)
        if normalized_language:
            normalized_messages[normalized_language] = message.strip()

    return normalized_messages


@lru_cache(maxsize=None)
def load_chatbot_content_filter_messages(chatbot_name: str) -> dict[str, str]:
    normalized_chatbot_name = normalize_chatbot_name(chatbot_name)
    if normalized_chatbot_name is None:
        return {}

    module_name = f"approaches.chatbots.{normalized_chatbot_name}.contentfilter"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name == module_name:
            return {}
        logger.exception("Failed to import chatbot content-filter module: %s", module_name)
        return {}
    except Exception:
        logger.exception("Failed to import chatbot content-filter module: %s", module_name)
        return {}

    return normalize_content_filter_messages(getattr(module, "CONTENT_FILTER_MESSAGES", None))


def get_content_filter_message(chatbot_name: Optional[str], language: Optional[str]) -> str:
    normalized_language = normalize_content_filter_language(language) or "en"
    chatbot_messages = load_chatbot_content_filter_messages(chatbot_name or "")

    if normalized_language in chatbot_messages:
        return chatbot_messages[normalized_language]
    if "en" in chatbot_messages:
        return chatbot_messages["en"]
    if normalized_language in DEFAULT_CONTENT_FILTER_MESSAGES:
        return DEFAULT_CONTENT_FILTER_MESSAGES[normalized_language]
    return DEFAULT_CONTENT_FILTER_MESSAGES["en"]
