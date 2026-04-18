from approaches.chatbot_config_registry import (
    get_chatbot_citation_target,
    get_chatbot_config,
    get_chatbot_prompt_mode,
    load_all_chatbot_configs,
    load_chatbot_config,
)
from approaches.chatbot_prompt_registry import get_registered_chatbot_names


def test_chatbot_config_registry_loads_known_configs() -> None:
    load_chatbot_config.cache_clear()

    nerilio = get_chatbot_config("nerilio")
    assert nerilio is not None
    assert nerilio.chatgpt_model == "gpt-4.1-mini"
    assert nerilio.chatgpt_deployment == "gpt-4.1-mini"
    assert nerilio.reasoning_effort is None
    assert nerilio.support_email == "hallo@nerilio.ai"
    assert nerilio.prompt_mode == "override"

    moodle = get_chatbot_config("moodle")
    assert moodle is not None
    assert moodle.citation_target == "url"
    assert moodle.prompt_mode == "override"

    vjoonk4 = get_chatbot_config("vjoonk4")
    assert vjoonk4 is not None
    assert vjoonk4.prompt_mode == "inject"

    lemon = get_chatbot_config("lemon")
    assert lemon is not None
    assert lemon.prompt_mode == "override"
    assert lemon.support_email == "info@lemon-systems.de"


def test_chatbot_config_registry_returns_defaults_for_unknown_chatbots() -> None:
    load_chatbot_config.cache_clear()

    assert get_chatbot_config("unknown-bot") is None
    assert get_chatbot_citation_target("unknown-bot") == "sourcepage"
    assert get_chatbot_prompt_mode("unknown-bot") == "override"


def test_load_all_chatbot_configs_discovers_only_bots_with_config_files() -> None:
    load_chatbot_config.cache_clear()

    configs = load_all_chatbot_configs()

    assert "internal" not in get_registered_chatbot_names()
    assert "internal" not in configs
    assert set(get_registered_chatbot_names()) == set(configs.keys())
