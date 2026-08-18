import logging
from functools import lru_cache
from importlib import import_module
from typing import Optional

logger = logging.getLogger(__name__)

# Keep in sync with frontend chatbot routes in app/frontend/src/chatbots/registry.ts.
DEFAULT_CHATBOT_NAME = "nerilio"
CHATBOT_NAME_ALIASES = {
    "public-test": "free",
}
CHATBOT_PROMPT_MODULES = {
    "agindo": "approaches.chatbots.agindo.sampleprompt",
    "bbsa": "approaches.chatbots.bbsa.sampleprompt",
    "bensberg": "approaches.chatbots.bensberg.sampleprompt",
    "cbtx": "approaches.chatbots.cbtx.sampleprompt",
    "nerilio": "approaches.chatbots.nerilio.sampleprompt",
    "snap": "approaches.chatbots.snap.sampleprompt",
    "free": "approaches.chatbots.free.sampleprompt",
    "rak": "approaches.chatbots.rak.sampleprompt",
    "sartorius": "approaches.chatbots.sartorius.sampleprompt",
    "steuertipps": "approaches.chatbots.steuertipps.sampleprompt",
    "knoll": "approaches.chatbots.knoll.sampleprompt",
    "lemon": "approaches.chatbots.lemon.sampleprompt",
    "hyrox-assessment": "approaches.chatbots.hyrox_assessment.sampleprompt",
    "moodle": "approaches.chatbots.moodle.sampleprompt",
    "publishone": "approaches.chatbots.publishone.sampleprompt",
    "publishone2": "approaches.chatbots.publishone2.sampleprompt",
    "fbn": "approaches.chatbots.fbn.sampleprompt",
    "demo": "approaches.chatbots.demo.sampleprompt",
    "fhg": "approaches.chatbots.fhg.sampleprompt",
    "vjoonk4": "approaches.chatbots.vjoonk4.sampleprompt",
}

# Every built-in (committed) chatbot name, i.e. everything that is NOT a provisioned/dynamic bot.
#
# This lives here rather than in app.py because app.py imports the approaches layer, so the reverse
# import would be a cycle. It is the canonical set for "is this category a built-in bot?" questions
# asked from inside the approaches layer; `app.KNOWN_CHATBOT_NAMES` is the routing-side mirror and
# `tests/test_chatbot_config_registry.py` pins the two equal so neither can drift.
#
# It is NOT the same as CHATBOT_PROMPT_MODULES: that map has no `internal` (a router shell with no
# prompt of its own) and no `public-test` (an alias of `free`), and both must count as built-in.
BUILTIN_CHATBOT_NAMES = frozenset(CHATBOT_PROMPT_MODULES) | frozenset(CHATBOT_NAME_ALIASES) | {
    DEFAULT_CHATBOT_NAME,
    "internal",
}


def normalize_chatbot_name(chatbot_name: Optional[str]) -> Optional[str]:
    if not chatbot_name:
        return None
    normalized = chatbot_name.strip().strip("/").lower()
    if not normalized:
        return None
    return CHATBOT_NAME_ALIASES.get(normalized, normalized)


def is_builtin_chatbot_name(chatbot_name: Optional[str]) -> bool:
    """Whether a name/category belongs to a committed bot rather than a provisioned one."""
    normalized = normalize_chatbot_name(chatbot_name)
    return normalized is not None and normalized in BUILTIN_CHATBOT_NAMES


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


def get_registered_chatbot_names() -> list[str]:
    return list(CHATBOT_PROMPT_MODULES)
