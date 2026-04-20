import logging
import re
from functools import lru_cache
from importlib import import_module
from typing import Optional

from approaches.chatbot_prompt_registry import CHATBOT_PROMPT_MODULES, normalize_chatbot_name
from approaches.chatbots.chatbot_config import ChatbotConfig

logger = logging.getLogger(__name__)
SUPPORT_EMAIL_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*SUPPORT_EMAIL\s*\}\}")
POSSIBLE_CITATIONS_PROMPT_PATTERN = re.compile(r"\{\{\s*POSSIBLE_CITATIONS_PROMPT\s*\}\}")
LANGUAGE_LOCALE_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*language_locale\s*\}\}")

LANGUAGE_CODE_TO_NAME = {
    "de": "German",
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
}

DEFAULT_LANGUAGE = "German"


def get_language_name(language_code: Optional[str]) -> str:
    if not language_code:
        logger.debug("get_language_name: language_code is None/empty, returning default: %s", DEFAULT_LANGUAGE)
        return DEFAULT_LANGUAGE
    normalized = language_code.strip().lower()
    # Handle language codes with region (e.g., "en-US" -> "en")
    if "-" in normalized:
        normalized = normalized.split("-")[0]
    result = LANGUAGE_CODE_TO_NAME.get(normalized, DEFAULT_LANGUAGE)
    logger.debug("get_language_name: input=%s, normalized=%s, result=%s", language_code, normalized, result)
    return result

# Maps chatbot names to their on-disk folder name when they differ.
CHATBOT_CONFIG_FOLDER_MAP: dict[str, str] = {
    "free": "public_test",
}


@lru_cache(maxsize=None)
def load_chatbot_config(chatbot_name: str) -> Optional[ChatbotConfig]:
    """Load the ChatbotConfig for a given chatbot name, or None if no config.py exists."""
    module_suffix = CHATBOT_CONFIG_FOLDER_MAP.get(chatbot_name, chatbot_name.replace("-", "_"))
    module_name = f"approaches.chatbots.{module_suffix}.config"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name == module_name:
            return None  # config.py simply doesn't exist — that's fine
        logger.exception("Failed to import chatbot config module: %s", module_name)
        return None
    except Exception:
        logger.exception("Failed to import chatbot config module: %s", module_name)
        return None

    cfg = getattr(module, "config", None)
    if not isinstance(cfg, ChatbotConfig):
        logger.warning("Chatbot config module %s does not export a ChatbotConfig as 'config'", module_name)
        return None
    return cfg


def get_chatbot_config(chatbot_name: Optional[str]) -> Optional[ChatbotConfig]:
    normalized = normalize_chatbot_name(chatbot_name)
    if not normalized:
        return None
    return load_chatbot_config(normalized)


def get_chatbot_citation_target(chatbot_name: Optional[str]) -> str:
    cfg = get_chatbot_config(chatbot_name)
    return cfg.citation_target if cfg else "sourcepage"


def get_chatbot_prompt_mode(chatbot_name: Optional[str]) -> str:
    cfg = get_chatbot_config(chatbot_name)
    return cfg.prompt_mode if cfg else "override"


def build_possible_citations_prompt(citations: Optional[list[str]]) -> str:
    if not citations:
        return ""
    possible_citations = " ".join(f"[{citation}]" for citation in citations if citation)
    if not possible_citations:
        return ""
    return f"Possible citations for current question: {possible_citations}"


def render_chatbot_prompt(
    prompt: str, chatbot_name: Optional[str], citations: Optional[list[str]] = None, language: Optional[str] = None
) -> str:
    normalized = normalize_chatbot_name(chatbot_name)
    if not prompt or not normalized:
        return prompt

    rendered_prompt = prompt
    cfg = get_chatbot_config(normalized)
    if SUPPORT_EMAIL_PLACEHOLDER_PATTERN.search(rendered_prompt):
        if cfg and cfg.support_email:
            rendered_prompt = SUPPORT_EMAIL_PLACEHOLDER_PATTERN.sub(cfg.support_email, rendered_prompt)
        else:
            logger.warning(
                "Chatbot prompt for %s references SUPPORT_EMAIL but chatbot config does not provide support_email",
                normalized,
            )

    if POSSIBLE_CITATIONS_PROMPT_PATTERN.search(rendered_prompt):
        possible_citations_prompt = build_possible_citations_prompt(citations)
        rendered_prompt = POSSIBLE_CITATIONS_PROMPT_PATTERN.sub(
            lambda _match: possible_citations_prompt,
            rendered_prompt,
        )

    if LANGUAGE_LOCALE_PLACEHOLDER_PATTERN.search(rendered_prompt):
        language_name = cfg.language_locale if cfg and cfg.language_locale else get_language_name(language)
        logger.info(
            "Language replacement: chatbot=%s, cfg_language_locale=%s, request_language=%s, final_language=%s",
            normalized,
            cfg.language_locale if cfg else "N/A",
            language,
            language_name,
        )
        rendered_prompt = LANGUAGE_LOCALE_PLACEHOLDER_PATTERN.sub(language_name, rendered_prompt)

    return rendered_prompt


def load_all_chatbot_configs() -> dict[str, ChatbotConfig]:
    """Return a dict of chatbot_name → ChatbotConfig for all bots that have a config.py."""
    configs: dict[str, ChatbotConfig] = {}
    for name in CHATBOT_PROMPT_MODULES:
        cfg = load_chatbot_config(name)
        if cfg is not None:
            configs[name] = cfg
    return configs
