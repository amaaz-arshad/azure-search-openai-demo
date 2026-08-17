from approaches.chatbot_config_registry import (
    get_chatbot_citation_target,
    get_chatbot_config,
    get_chatbot_prompt_mode,
    load_all_chatbot_configs,
    load_chatbot_config,
    render_chatbot_prompt,
)
from approaches.chatbot_prompt_registry import get_chatbot_prompt, get_registered_chatbot_names


def test_chatbot_config_registry_loads_known_configs() -> None:
    load_chatbot_config.cache_clear()

    nerilio = get_chatbot_config("nerilio")
    assert nerilio is not None
    assert nerilio.chatgpt_model == "gpt-4.1"
    assert nerilio.chatgpt_deployment == "gpt-4.1"
    assert nerilio.reasoning_effort is None
    assert nerilio.support_email == "hallo@nerilio.ai"
    assert nerilio.prompt_mode == "override"

    snap = get_chatbot_config("snap")
    assert snap is not None
    assert snap.chatgpt_model == "gpt-4.1"
    assert snap.support_email == "info@snap.de"
    assert snap.citation_target == "url"
    assert snap.prompt_mode == "override"

    moodle = get_chatbot_config("moodle")
    assert moodle is not None
    assert moodle.citation_target == "url"
    assert moodle.prompt_mode == "override"

    publishone = get_chatbot_config("publishone")
    assert publishone is not None
    assert publishone.language_locale == "English"
    assert publishone.citation_target == "url"
    assert publishone.prompt_mode == "override"

    vjoonk4 = get_chatbot_config("vjoonk4")
    assert vjoonk4 is not None
    assert vjoonk4.prompt_mode == "inject"

    lemon = get_chatbot_config("lemon")
    assert lemon is not None
    assert lemon.prompt_mode == "override"
    assert lemon.support_email == "info@lemon-systems.de"

    bensberg = get_chatbot_config("bensberg")
    assert bensberg is not None
    assert bensberg.prompt_mode == "override"
    assert bensberg.support_email == "info@lemon-systems.de"

    bbsa = get_chatbot_config("bbsa")
    assert bbsa is not None
    assert bbsa.chatgpt_model == "gpt-4.1"
    assert bbsa.language_locale == "German"
    assert bbsa.support_email == "office@bbsa.tirol"
    # The bbsa corpus is scraped web content: every record carries the live breitband.tirol
    # (or <gemeinde>.breitband.tirol) URL, so citations must resolve to the public page.
    assert bbsa.citation_target == "url"
    assert bbsa.prompt_mode == "override"


def test_render_bbsa_prompt_locks_german_and_keeps_municipality_attribution_rules() -> None:
    load_chatbot_config.cache_clear()
    bbsa_prompt = get_chatbot_prompt("bbsa")
    assert bbsa_prompt is not None
    # prompt_mode="override" bypasses the base RAG citation instructions, so the prompt itself
    # must opt in to citations.
    assert "Use square brackets to reference the source" in bbsa_prompt
    assert "{{POSSIBLE_CITATIONS_PROMPT}}" in bbsa_prompt
    # The corpus holds one document per municipality with contradictory rules (who pays for the
    # house connection, which providers sell service). Transferring one municipality's rule to
    # another is the bot's main accuracy risk, so the prompt must forbid it explicitly.
    assert "Municipality-Specific Answers" in bbsa_prompt
    assert "NEVER transferable between municipalities" in bbsa_prompt

    rendered = render_chatbot_prompt(
        bbsa_prompt,
        "bbsa",
        citations=["https://schwoich.breitband.tirol/gemeindeinfos/"],
    )

    # The url citation_target means the possible-citation labels are live breitband.tirol URLs —
    # which is also what carries the municipality identity into every chunk's source label.
    assert "Possible citations for current question: [https://schwoich.breitband.tirol/gemeindeinfos/]" in rendered
    # Placeholders are fully substituted (no leftover template tokens).
    assert "{{POSSIBLE_CITATIONS_PROMPT}}" not in rendered
    assert "{{SUPPORT_EMAIL}}" not in rendered
    assert "{{language_locale}}" not in rendered
    assert "office@bbsa.tirol" in rendered
    # language_locale is code-substituted from config.py, locking answers to German.
    assert "Always respond in German" in rendered


def test_chatbot_config_registry_returns_defaults_for_unknown_chatbots() -> None:
    load_chatbot_config.cache_clear()

    assert get_chatbot_config("unknown-bot") is None
    assert get_chatbot_citation_target("unknown-bot") == "sourcepage"
    assert get_chatbot_prompt_mode("unknown-bot") == "override"


def test_snap_prompt_requests_url_citations_instead_of_suppressing_them() -> None:
    # snap uses prompt_mode="override", so the base RAG citation instructions are
    # bypassed and the prompt itself must opt in to citations. It previously cloned
    # nerilio's "Do not include citations" line, which suppressed all references.
    snap_prompt = get_chatbot_prompt("snap")
    assert snap_prompt is not None
    assert "Do **not** include citations" not in snap_prompt
    assert "Use square brackets to reference the source" in snap_prompt
    assert "{{POSSIBLE_CITATIONS_PROMPT}}" in snap_prompt


def test_render_snap_prompt_injects_url_citations_and_support_email() -> None:
    load_chatbot_config.cache_clear()
    snap_prompt = get_chatbot_prompt("snap")
    assert snap_prompt is not None

    rendered = render_chatbot_prompt(
        snap_prompt,
        "snap",
        citations=["https://www.snap.de/tools/nerilio/"],
    )

    # The url citation_target means the possible-citation labels are live snap.de URLs.
    assert "Possible citations for current question: [https://www.snap.de/tools/nerilio/]" in rendered
    # Placeholders are fully substituted (no leftover template tokens).
    assert "{{POSSIBLE_CITATIONS_PROMPT}}" not in rendered
    assert "{{SUPPORT_EMAIL}}" not in rendered
    assert "info@snap.de" in rendered


def test_load_all_chatbot_configs_discovers_only_bots_with_config_files() -> None:
    load_chatbot_config.cache_clear()

    configs = load_all_chatbot_configs()

    assert "internal" not in get_registered_chatbot_names()
    assert "internal" not in configs
    assert set(get_registered_chatbot_names()) == set(configs.keys())


def test_speech_voice_is_opt_in_per_bot() -> None:
    """AZURE_SPEECH_SERVICE_VOICE is deployment-wide and shared by every speech-enabled bot, so a
    bot that needs a different speak-answer voice declares it here instead. Only bbsa does today —
    if that changes, make sure it was deliberate, because every other bot silently inherits the
    deployment voice from a `None` here."""
    load_chatbot_config.cache_clear()

    configs = load_all_chatbot_configs()

    bbsa_config = configs.get("bbsa")
    assert bbsa_config is not None
    # Austrian German, matching the live avatar's voice.
    assert bbsa_config.speech_voice == "de-AT-JonasNeural"

    overriding_bots = {name for name, config in configs.items() if config.speech_voice}
    assert overriding_bots == {"bbsa"}, overriding_bots
