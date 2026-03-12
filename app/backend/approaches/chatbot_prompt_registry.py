import logging
from functools import lru_cache
from importlib import import_module
from typing import Optional

logger = logging.getLogger(__name__)

# Keep in sync with frontend chatbot routes in app/frontend/src/chatbots/registry.ts.
DEFAULT_CHATBOT_NAME = "nerilio"
CHATBOT_PROMPT_MODULES = {
    "nerilio": "approaches.chatbots.nerilio.sampleprompt",
    "steuertipps": "approaches.chatbots.steuertipps.sampleprompt",
    "knoll": "approaches.chatbots.knoll.sampleprompt",
    "lemon": "approaches.chatbots.lemon.sampleprompt",
    "publishone": "approaches.chatbots.publishone.sampleprompt",
    "fbn": "approaches.chatbots.fbn.sampleprompt",
    "demo": "approaches.chatbots.demo.sampleprompt",
    "fhg": "approaches.chatbots.fhg.sampleprompt",
}


def normalize_chatbot_name(chatbot_name: Optional[str]) -> Optional[str]:
    if not chatbot_name:
        return None
    normalized = chatbot_name.strip().strip("/").lower()
    return normalized or None


@lru_cache(maxsize=None)
def load_prompt_from_module(module_name: str) -> Optional[str]:
    try:
        module = import_module(module_name)
    except Exception:
        logger.exception("Failed to import chatbot prompt module: %s", module_name)
        return None

    prompt = getattr(module, "SAMPLE_PROMPT", None)
    if isinstance(prompt, str) and prompt.strip():
        return prompt
    return None


def get_chatbot_prompt(chatbot_name: Optional[str]) -> Optional[str]:
    normalized_name = normalize_chatbot_name(chatbot_name) or DEFAULT_CHATBOT_NAME
    module_name = CHATBOT_PROMPT_MODULES.get(normalized_name)
    if not module_name:
        return None
    return load_prompt_from_module(module_name)
