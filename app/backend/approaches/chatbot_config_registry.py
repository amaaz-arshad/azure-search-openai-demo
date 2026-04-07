import logging
import re
from functools import lru_cache
from importlib import import_module
from typing import Optional

from approaches.chatbot_prompt_registry import CHATBOT_PROMPT_MODULES, normalize_chatbot_name
from approaches.chatbots.chatbot_config import ChatbotConfig

logger = logging.getLogger(__name__)
SUPPORT_EMAIL_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*SUPPORT_EMAIL\s*\}\}")


@lru_cache(maxsize=None)
def load_chatbot_config(chatbot_name: str) -> Optional[ChatbotConfig]:
    """Load the ChatbotConfig for a given chatbot name, or None if no config.py exists."""
    # public-test is stored as public_test on disk
    module_suffix = chatbot_name.replace("-", "_")
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


def render_chatbot_prompt(prompt: str, chatbot_name: Optional[str]) -> str:
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

    return rendered_prompt


def load_all_chatbot_configs() -> dict[str, ChatbotConfig]:
    """Return a dict of chatbot_name → ChatbotConfig for all bots that have a config.py."""
    configs: dict[str, ChatbotConfig] = {}
    for name in CHATBOT_PROMPT_MODULES:
        cfg = load_chatbot_config(name)
        if cfg is not None:
            configs[name] = cfg
    return configs
