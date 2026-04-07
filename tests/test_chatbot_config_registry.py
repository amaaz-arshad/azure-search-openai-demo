from approaches.chatbot_config_registry import (
    get_chatbot_citation_target,
    get_chatbot_config,
    load_all_chatbot_configs,
    load_chatbot_config,
)


def test_chatbot_config_registry_loads_known_configs() -> None:
    load_chatbot_config.cache_clear()

    nerilio = get_chatbot_config("nerilio")
    assert nerilio is not None
    assert nerilio.chatgpt_model == "gpt-4.1-nano"
    assert nerilio.chatgpt_deployment == "gpt-4.1-nano"
    assert nerilio.reasoning_effort is None

    moodle = get_chatbot_config("moodle")
    assert moodle is not None
    assert moodle.citation_target == "url"


def test_chatbot_config_registry_returns_defaults_for_unknown_chatbots() -> None:
    load_chatbot_config.cache_clear()

    assert get_chatbot_config("unknown-bot") is None
    assert get_chatbot_citation_target("unknown-bot") == "sourcepage"


def test_load_all_chatbot_configs_discovers_only_bots_with_config_files() -> None:
    load_chatbot_config.cache_clear()

    configs = load_all_chatbot_configs()

    assert {"fhg", "moodle", "nerilio", "publishone"}.issubset(configs.keys())
    assert "demo" not in configs
    assert "rak" not in configs
