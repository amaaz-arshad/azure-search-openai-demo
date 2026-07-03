"""Map a dynamic chatbot's registry record onto the runtime config its frontend needs.

The generic dynamic-bot frontend (Phase 3) bootstraps from GET /bot-config/<name>, which returns
this payload. Built-in bots never use this — they have their config baked into the source registry;
/bot-config resolves dynamic bots only.

The mapping normalizes the control-panel vocabulary to what the frontend expects: language LABELS
("Deutsch") -> ISO codes ("de"), and the modes flags -> the frontend ChatbotMode string. `assessment`
is intentionally ignored (always false per the agreed contract — no generic MC engine exists).
"""

from typing import Any, Optional

from core.chatbotregistrystore import ChatbotRegistryRecord
from core.dynamic_tutor_prompt import DEFAULT_DYNAMIC_TUTOR_PROMPT

# Supported frontend locales (must match the en/de/nl standard). Order is the default-preference order.
SUPPORTED_LANGUAGE_CODES: tuple[str, ...] = ("de", "en", "nl")

# Mode-aware default chat models for dynamic bots whose provisioned `llm` is empty, unknown, or not
# deployed here. Tutor bots need a reasoning-capable model (run at high effort); Q&A bots use a
# cheaper general model. These are model IDs from `DEVELOPER_CHAT_MODELS`; the matching Azure
# deployments must exist (or `AZURE_OPENAI_CHAT_MODEL_DEPLOYMENTS` must map them) for them to serve.
DEFAULT_DYNAMIC_TUTOR_MODEL = "gpt-5.4"
DEFAULT_DYNAMIC_QNA_MODEL = "gpt-4.1"

# Control-panel language labels (and a few aliases) -> frontend locale code.
LANGUAGE_LABEL_TO_CODE: dict[str, str] = {
    "de": "de",
    "deutsch": "de",
    "german": "de",
    "en": "en",
    "english": "en",
    "englisch": "en",
    "nl": "nl",
    "nederlands": "nl",
    "dutch": "nl",
    "niederlaendisch": "nl",
    "niederländisch": "nl",
}

DEFAULT_LANGUAGE_CODE = "de"

# `ansprache` (formal/informal addressing) is a structured field the control panel sets
# independently of the prompt text. Built-in bots hardcode informal "du"; dynamic bots honor the
# configured value by appending a directive to their system prompt. The nerilio backend sends
# "informal"/"formal"; "du"/"sie" are accepted as aliases. The directive is language-general:
# explicit forms for German and Dutch (the T-V locales this deployment serves), a generic rule for
# any other language with a formal/informal distinction, and a tone rule for languages without one
# (English), so it holds whatever language the answer ends up in.
INFORMAL_ANSPRACHE_DIRECTIVE = (
    "Always address the user informally, whatever language you are answering in. Where the "
    "language distinguishes informal from formal address, use the informal form: in German "
    "du/dich/dir/dein (never the formal Sie/Ihnen/Ihr), in Dutch je/jij/jou/jouw (never the "
    "formal u/uw), and the equivalent informal second person in any other such language "
    "(e.g. French tu, Spanish tú, Italian tu). In languages without this distinction, such as "
    "English, use a friendly, casual tone."
)
FORMAL_ANSPRACHE_DIRECTIVE = (
    "Always address the user formally, whatever language you are answering in. Where the "
    "language distinguishes formal from informal address, use the formal form: in German "
    "Sie/Ihnen/Ihr (never the informal du/dich/dir/dein), in Dutch u/uw (never the informal "
    "je/jij/jou), and the equivalent formal second person in any other such language "
    "(e.g. French vous, Spanish usted, Italian Lei). In languages without this distinction, "
    "such as English, use a polite, professional tone."
)
ANSPRACHE_DIRECTIVES: dict[str, str] = {
    "informal": INFORMAL_ANSPRACHE_DIRECTIVE,
    "du": INFORMAL_ANSPRACHE_DIRECTIVE,
    "formal": FORMAL_ANSPRACHE_DIRECTIVE,
    "sie": FORMAL_ANSPRACHE_DIRECTIVE,
}


def ansprache_directive(ansprache: Any) -> Optional[str]:
    """Map an `ansprache` value to a system-prompt addressing directive, or None if unset/unknown."""
    if not isinstance(ansprache, str):
        return None
    return ANSPRACHE_DIRECTIVES.get(ansprache.strip().lower())


def build_dynamic_system_prompt(record: ChatbotRegistryRecord, default_prompt: str) -> str:
    """Build a dynamic bot's effective system prompt: its custom prompt when provided, otherwise a
    mode-aware default (the generic tutor prompt for tutor bots, else the neutral Q&A ``default_prompt``),
    with the configured `ansprache` addressing directive appended when set."""
    custom_prompt = (record.prompt or "").strip()
    if custom_prompt:
        base = custom_prompt
    elif derive_chatbot_mode(record.modes) == "tutor-qna":
        base = DEFAULT_DYNAMIC_TUTOR_PROMPT
    else:
        base = default_prompt
    directive = ansprache_directive(record.ansprache)
    return f"{base}\n\n{directive}" if directive else base


def language_label_to_code(label: Any) -> Optional[str]:
    """Map a language label/code to a supported frontend locale code, or None if unsupported."""
    if not isinstance(label, str):
        return None
    return LANGUAGE_LABEL_TO_CODE.get(label.strip().lower())


def map_language_list(labels: Any) -> list[str]:
    """Map a list of language labels to deduped supported codes, preserving order."""
    codes: list[str] = []
    if isinstance(labels, list):
        for label in labels:
            code = language_label_to_code(label)
            if code is not None and code not in codes:
                codes.append(code)
    return codes


def map_language_keyed(mapping: Any) -> dict[str, str]:
    """Re-key a {language-label: text} map to {locale-code: text} for supported codes only."""
    result: dict[str, str] = {}
    if isinstance(mapping, dict):
        for label, value in mapping.items():
            code = language_label_to_code(label)
            if code is not None and isinstance(value, str):
                result[code] = value
    return result


def derive_chatbot_mode(modes: Any) -> str:
    """Derive the frontend ChatbotMode ("qna" | "tutor-qna") from the modes flags.

    assessment is ignored (always false per contract). tutor enabled -> dual "tutor-qna"; else "qna".
    """
    if isinstance(modes, dict) and modes.get("tutor"):
        return "tutor-qna"
    return "qna"


def build_bot_config_payload(record: ChatbotRegistryRecord) -> dict[str, Any]:
    """Build the GET /bot-config/<name> response for an active dynamic bot.

    Deliberately excludes the system prompt and other internals — this is the public-ish display
    contract the frontend bootstraps from (theme, greeting, disclaimer, mode, languages, login).
    """
    languages = map_language_list(record.languages) or [DEFAULT_LANGUAGE_CODE]
    design = record.design if isinstance(record.design, dict) else {}
    return {
        "botName": record.bot_name,
        "displayName": record.display_name,
        "mode": derive_chatbot_mode(record.modes),
        "llm": record.llm,
        "primaryColor": design.get("color_primary"),
        "languages": languages,
        "defaultLanguage": languages[0],
        "greeting": map_language_keyed(record.greeting),
        "disclaimer": map_language_keyed(record.disclaimer),
        "features": record.features if isinstance(record.features, dict) else {},
        "login": record.login if isinstance(record.login, dict) else {},
    }
