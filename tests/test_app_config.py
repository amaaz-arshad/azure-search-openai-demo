import os
import sys
from unittest import mock

import pytest
import quart

import app
from approaches.chatbots.chatbot_config import ChatbotConfig


@pytest.fixture
def minimal_env(monkeypatch):
    with mock.patch.dict(os.environ, clear=True):
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT", "test-storage-account")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "test-storage-container")
        monkeypatch.setenv("AZURE_SEARCH_INDEX", "test-search-index")
        monkeypatch.setenv("AZURE_SEARCH_SERVICE", "test-search-service")
        monkeypatch.setenv("AZURE_OPENAI_SERVICE", "test-openai-service")
        monkeypatch.setenv("AZURE_OPENAI_CHATGPT_MODEL", "gpt-4.1-mini")
        monkeypatch.setenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT", "test-chat-deployment")
        monkeypatch.setenv("AZURE_OPENAI_EMB_MODEL_NAME", "text-embedding-3-large")
        monkeypatch.setenv("AZURE_OPENAI_EMB_DIMENSIONS", "3072")
        monkeypatch.setenv("AZURE_OPENAI_EMB_DEPLOYMENT", "test-emb-deployment")
        yield


@pytest.mark.asyncio
async def test_app_local_openai(monkeypatch, minimal_env):
    monkeypatch.setenv("OPENAI_HOST", "local")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:5000")

    quart_app = app.create_app()
    async with quart_app.test_app():
        assert quart_app.config[app.CONFIG_OPENAI_CLIENT].api_key == "no-key-required"
        assert quart_app.config[app.CONFIG_OPENAI_CLIENT].base_url == "http://localhost:5000"


@pytest.mark.asyncio
async def test_app_azure_custom_key(monkeypatch, minimal_env):
    monkeypatch.setenv("OPENAI_HOST", "azure_custom")
    monkeypatch.setenv("AZURE_OPENAI_CUSTOM_URL", "http://azureapi.com/api/v1")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY_OVERRIDE", "azure-api-key")

    quart_app = app.create_app()
    async with quart_app.test_app():
        assert quart_app.config[app.CONFIG_OPENAI_CLIENT].api_key == "azure-api-key"
        assert quart_app.config[app.CONFIG_OPENAI_CLIENT].base_url == "http://azureapi.com/api/v1/"


@pytest.mark.asyncio
async def test_app_azure_custom_identity(monkeypatch, minimal_env):
    monkeypatch.setenv("OPENAI_HOST", "azure_custom")
    monkeypatch.setenv("AZURE_OPENAI_CUSTOM_URL", "http://azureapi.com/api/v1")

    quart_app = app.create_app()
    async with quart_app.test_app():
        openai_client = quart_app.config[app.CONFIG_OPENAI_CLIENT]
        assert openai_client.api_key == ""
        # The AsyncOpenAI client stores the callable inside _api_key_provider
        assert getattr(openai_client, "_api_key_provider", None) is not None
        assert str(openai_client.base_url) == "http://azureapi.com/api/v1/"


@pytest.mark.asyncio
async def test_app_user_upload_processors(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_USERSTORAGE_ACCOUNT", "test-user-storage-account")
    monkeypatch.setenv("AZURE_USERSTORAGE_CONTAINER", "test-user-storage-container")
    monkeypatch.setenv("AZURE_ENFORCE_ACCESS_CONTROL", "true")
    monkeypatch.setenv("USE_USER_UPLOAD", "true")

    quart_app = app.create_app()
    async with quart_app.test_app():
        ingester = quart_app.config[app.CONFIG_INGESTER]
        assert ingester is not None
        assert len(ingester.file_processors.keys()) == 7


@pytest.mark.asyncio
async def test_app_demo_upload_processors_are_local(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_DOCUMENTINTELLIGENCE_SERVICE", "test-docint-service")

    quart_app = app.create_app()
    async with quart_app.test_app():
        chatbot_upload_managers = quart_app.config[app.CONFIG_CHATBOT_UPLOAD_MANAGERS]
        demo_upload_manager = chatbot_upload_managers["demo"]
        assert demo_upload_manager is not None
        assert sorted(demo_upload_manager.file_processors.keys()) == [
            ".csv",
            ".html",
            ".json",
            ".md",
            ".pdf",
            ".txt",
            ".xml",
        ]


@pytest.mark.asyncio
async def test_app_chatbot_upload_managers_exclude_internal_router(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_SERVER_APP_SECRET", "test-server-secret")
    quart_app = app.create_app()
    async with quart_app.test_app():
        chatbot_upload_managers = quart_app.config[app.CONFIG_CHATBOT_UPLOAD_MANAGERS]
        assert set(chatbot_upload_managers) == {"demo", "free", "rak"}


@pytest.mark.asyncio
async def test_app_free_upload_manager_uses_20_mb_pdf_limit(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_SERVER_APP_SECRET", "test-server-secret")
    quart_app = app.create_app()
    async with quart_app.test_app():
        free_upload_manager = quart_app.config[app.CONFIG_CHATBOT_UPLOAD_MANAGERS]["free"]
        assert free_upload_manager.rules.allowed_extensions == frozenset({".pdf"})
        assert free_upload_manager.rules.max_total_file_size_mb == 20
        assert free_upload_manager.rules.max_total_file_count == 1
        assert free_upload_manager.rules.max_total_pdf_pages is None


@pytest.mark.asyncio
async def test_app_user_upload_requires_storage_configuration(monkeypatch, minimal_env):
    monkeypatch.setenv("USE_USER_UPLOAD", "true")

    quart_app = app.create_app()
    with pytest.raises(
        quart.testing.app.LifespanError,
        match="AZURE_USERSTORAGE_ACCOUNT and AZURE_USERSTORAGE_CONTAINER must be set when USE_USER_UPLOAD is true",
    ):
        async with quart_app.test_app():
            pass


@pytest.mark.asyncio
async def test_app_user_upload_requires_enforce_access_control(monkeypatch, minimal_env):
    monkeypatch.setenv("USE_USER_UPLOAD", "true")
    monkeypatch.setenv("AZURE_USERSTORAGE_ACCOUNT", "test-user-storage-account")
    monkeypatch.setenv("AZURE_USERSTORAGE_CONTAINER", "test-user-storage-container")

    quart_app = app.create_app()
    with pytest.raises(
        quart.testing.app.LifespanError,
        match="AZURE_ENFORCE_ACCESS_CONTROL must be true when USE_USER_UPLOAD is true",
    ):
        async with quart_app.test_app():
            pass


@pytest.mark.asyncio
async def test_app_user_upload_processors_docint(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_USERSTORAGE_ACCOUNT", "test-user-storage-account")
    monkeypatch.setenv("AZURE_USERSTORAGE_CONTAINER", "test-user-storage-container")
    monkeypatch.setenv("AZURE_ENFORCE_ACCESS_CONTROL", "true")
    monkeypatch.setenv("USE_USER_UPLOAD", "true")
    monkeypatch.setenv("AZURE_DOCUMENTINTELLIGENCE_SERVICE", "test-docint-service")

    quart_app = app.create_app()
    async with quart_app.test_app():
        ingester = quart_app.config[app.CONFIG_INGESTER]
        assert ingester is not None
        assert len(ingester.file_processors.keys()) == 16


@pytest.mark.asyncio
async def test_app_user_upload_processors_docint_localpdf(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_USERSTORAGE_ACCOUNT", "test-user-storage-account")
    monkeypatch.setenv("AZURE_USERSTORAGE_CONTAINER", "test-user-storage-container")
    monkeypatch.setenv("AZURE_ENFORCE_ACCESS_CONTROL", "true")
    monkeypatch.setenv("USE_USER_UPLOAD", "true")
    monkeypatch.setenv("AZURE_DOCUMENTINTELLIGENCE_SERVICE", "test-docint-service")
    monkeypatch.setenv("USE_LOCAL_PDF_PARSER", "true")

    quart_app = app.create_app()
    async with quart_app.test_app():
        ingester = quart_app.config[app.CONFIG_INGESTER]
        assert ingester is not None
        assert len(ingester.file_processors.keys()) == 16
        assert ingester.file_processors[".pdf"] is not ingester.file_processors[".pptx"]


@pytest.mark.asyncio
async def test_app_user_upload_processors_docint_localhtml(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_USERSTORAGE_ACCOUNT", "test-user-storage-account")
    monkeypatch.setenv("AZURE_USERSTORAGE_CONTAINER", "test-user-storage-container")
    monkeypatch.setenv("AZURE_ENFORCE_ACCESS_CONTROL", "true")
    monkeypatch.setenv("USE_USER_UPLOAD", "true")
    monkeypatch.setenv("AZURE_DOCUMENTINTELLIGENCE_SERVICE", "test-docint-service")
    monkeypatch.setenv("USE_LOCAL_HTML_PARSER", "true")

    quart_app = app.create_app()
    async with quart_app.test_app():
        ingester = quart_app.config[app.CONFIG_INGESTER]
        assert ingester is not None
        assert len(ingester.file_processors.keys()) == 16
        assert ingester.file_processors[".html"] is not ingester.file_processors[".pptx"]


@pytest.mark.asyncio
async def test_app_config_default(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_SERVER_APP_SECRET", "test-server-secret")
    quart_app = app.create_app()
    async with quart_app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.get("/config")
        assert response.status_code == 200
        result = await response.get_json()
        assert result["availableChatModels"] == [
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
        ]
        assert result["defaultChatModel"] == "gpt-4.1-mini"
        assert result["internalSourceBots"] == [
            {"id": "agindo", "label": "agindo"},
            {"id": "bensberg", "label": "bensberg"},
            {"id": "demo", "label": "demo"},
            {"id": "fbn", "label": "fbn"},
            {"id": "fhg", "label": "fhg"},
            {"id": "knoll", "label": "knoll"},
            {"id": "lemon", "label": "lemon"},
            {"id": "moodle", "label": "moodle"},
            {"id": "nerilio", "label": "nerilio"},
            {"id": "publishone", "label": "publishone"},
            {"id": "sartorius", "label": "sartorius"},
            {"id": "steuertipps", "label": "steuertipps"},
            {"id": "vjoonk4", "label": "vjoonk4"},
        ]
        assert result["showMultimodalOptions"] is False
        assert result["showSemanticRankerOption"] is True
        assert result["showVectorOption"] is True
        assert result["defaultRetrievalReasoningEffort"] == "low"
        assert result["reasoningCapableChatModels"] == [
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
        ]
        assert result["chatModelReasoningEfforts"] == {
            "gpt-5": ["minimal", "low", "medium", "high"],
            "gpt-5-mini": ["minimal", "low", "medium", "high"],
            "gpt-5-nano": ["minimal", "low", "medium", "high"],
            "gpt-5.4": ["none", "low", "medium", "high", "xhigh"],
            "gpt-5.4-mini": ["none", "low", "medium", "high", "xhigh"],
            "gpt-5.4-nano": ["none", "low", "medium", "high", "xhigh"],
        }


@pytest.mark.asyncio
async def test_app_config_use_vectors_true(monkeypatch, minimal_env):
    monkeypatch.setenv("USE_VECTORS", "true")
    quart_app = app.create_app()
    async with quart_app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.get("/config")
        assert response.status_code == 200
        result = await response.get_json()
        assert result["showMultimodalOptions"] is False
        assert result["showSemanticRankerOption"] is True
        assert result["showVectorOption"] is True


@pytest.mark.asyncio
async def test_app_config_use_vectors_false(monkeypatch, minimal_env):
    monkeypatch.setenv("USE_VECTORS", "false")
    quart_app = app.create_app()
    async with quart_app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.get("/config")
        assert response.status_code == 200
        result = await response.get_json()
        assert result["showMultimodalOptions"] is False
        assert result["showSemanticRankerOption"] is True
        assert result["showVectorOption"] is False


@pytest.mark.asyncio
async def test_app_config_semanticranker_free(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_SEARCH_SEMANTIC_RANKER", "free")
    quart_app = app.create_app()
    async with quart_app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.get("/config")
        assert response.status_code == 200
        result = await response.get_json()
        assert result["showMultimodalOptions"] is False
        assert result["showSemanticRankerOption"] is True
        assert result["showVectorOption"] is True
        assert result["showUserUpload"] is False


@pytest.mark.asyncio
async def test_app_config_semanticranker_disabled(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_SEARCH_SEMANTIC_RANKER", "disabled")
    quart_app = app.create_app()
    async with quart_app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.get("/config")
        assert response.status_code == 200
        result = await response.get_json()
        assert result["showMultimodalOptions"] is False
        assert result["showSemanticRankerOption"] is False
        assert result["showVectorOption"] is True
        assert result["showUserUpload"] is False


@pytest.mark.asyncio
async def test_app_config_user_upload(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_USERSTORAGE_ACCOUNT", "test-user-storage-account")
    monkeypatch.setenv("AZURE_USERSTORAGE_CONTAINER", "test-user-storage-container")
    monkeypatch.setenv("AZURE_ENFORCE_ACCESS_CONTROL", "true")
    monkeypatch.setenv("USE_USER_UPLOAD", "true")
    quart_app = app.create_app()
    async with quart_app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.get("/config")
        assert response.status_code == 200
        result = await response.get_json()
        assert result["showMultimodalOptions"] is False
        assert result["showSemanticRankerOption"] is True
        assert result["showVectorOption"] is True
        assert result["showUserUpload"] is True


@pytest.mark.asyncio
async def test_app_config_user_upload_novectors(monkeypatch, minimal_env):
    """Check that this combo works correctly with prepdocs.py embedding service."""
    monkeypatch.setenv("AZURE_USERSTORAGE_ACCOUNT", "test-user-storage-account")
    monkeypatch.setenv("AZURE_USERSTORAGE_CONTAINER", "test-user-storage-container")
    monkeypatch.setenv("AZURE_ENFORCE_ACCESS_CONTROL", "true")
    monkeypatch.setenv("USE_USER_UPLOAD", "true")
    monkeypatch.setenv("USE_VECTORS", "false")
    quart_app = app.create_app()
    async with quart_app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.get("/config")
        assert response.status_code == 200
        result = await response.get_json()
        assert result["showMultimodalOptions"] is False
        assert result["showSemanticRankerOption"] is True
        assert result["showVectorOption"] is False
        assert result["showUserUpload"] is True


@pytest.mark.asyncio
async def test_app_config_user_upload_bad_openai_config(monkeypatch, minimal_env):
    """Check that this combo works correctly with prepdocs.py embedding service."""
    monkeypatch.setenv("AZURE_USERSTORAGE_ACCOUNT", "test-user-storage-account")
    monkeypatch.setenv("AZURE_USERSTORAGE_CONTAINER", "test-user-storage-container")
    monkeypatch.setenv("AZURE_ENFORCE_ACCESS_CONTROL", "true")
    monkeypatch.setenv("USE_USER_UPLOAD", "true")
    monkeypatch.setenv("OPENAI_HOST", "openai")
    quart_app = app.create_app()
    with pytest.raises(
        quart.testing.app.LifespanError, match="OpenAI key is required when using the non-Azure OpenAI API"
    ):
        async with quart_app.test_app() as test_app:
            test_app.test_client()


@pytest.mark.asyncio
async def test_app_config_user_upload_openaicom(monkeypatch, minimal_env):
    """Check that this combo works correctly with prepdocs.py embedding service."""
    monkeypatch.setenv("AZURE_USERSTORAGE_ACCOUNT", "test-user-storage-account")
    monkeypatch.setenv("AZURE_USERSTORAGE_CONTAINER", "test-user-storage-container")
    monkeypatch.setenv("AZURE_ENFORCE_ACCESS_CONTROL", "true")
    monkeypatch.setenv("USE_USER_UPLOAD", "true")
    monkeypatch.setenv("OPENAI_HOST", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "pretendkey")
    quart_app = app.create_app()
    async with quart_app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.get("/config")
        assert response.status_code == 200
        result = await response.get_json()
        assert result["showUserUpload"] is True


@pytest.mark.asyncio
async def test_app_config_for_client(client):
    response = await client.get("/config")
    assert response.status_code == 200
    result = await response.get_json()
    assert result["showMultimodalOptions"] == (os.getenv("USE_MULTIMODAL") == "true")
    assert result["showSemanticRankerOption"] is True
    assert result["showVectorOption"] is True
    assert result["streamingEnabled"] is True
    assert result["showReasoningEffortOption"] is False


@pytest.mark.asyncio
async def test_app_config_for_reasoning(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_OPENAI_CHATGPT_MODEL", "o3-mini")
    monkeypatch.setenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT", "o3-mini")
    quart_app = app.create_app()
    async with quart_app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.get("/config")
        assert response.status_code == 200
        result = await response.get_json()
        assert result["streamingEnabled"] is True
        assert result["showReasoningEffortOption"] is True


@pytest.mark.asyncio
async def test_app_config_for_reasoning_without_streaming(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_OPENAI_CHATGPT_MODEL", "o1")
    monkeypatch.setenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT", "o1")
    quart_app = app.create_app()
    async with quart_app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.get("/config")
        assert response.status_code == 200
        result = await response.get_json()
        assert result["streamingEnabled"] is False
        assert result["showReasoningEffortOption"] is True


@pytest.mark.asyncio
async def test_app_config_for_reasoning_override_effort(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "low")
    monkeypatch.setenv("AZURE_OPENAI_CHATGPT_MODEL", "o3-mini")
    monkeypatch.setenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT", "o3-mini")
    quart_app = app.create_app()
    async with quart_app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.get("/config")
        assert response.status_code == 200
        result = await response.get_json()
        assert result["streamingEnabled"] is True
        assert result["showReasoningEffortOption"] is True
        assert result["defaultReasoningEffort"] == "low"


@pytest.mark.asyncio
async def test_app_creates_chatbot_override_for_nerilio_config(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_SERVER_APP_SECRET", "test-server-secret")
    quart_app = app.create_app()

    async with quart_app.test_app():
        chatbot_approaches = quart_app.config[app.CONFIG_CHATBOT_CHAT_APPROACHES]

        assert "nerilio" in chatbot_approaches
        assert "moodle" not in chatbot_approaches
        assert "publishone" not in chatbot_approaches
        assert "fhg" not in chatbot_approaches

        nerilio_approach = chatbot_approaches["nerilio"]
        assert nerilio_approach.chatgpt_model == "gpt-4.1-nano"
        assert nerilio_approach.chatgpt_deployment == "gpt-4.1-nano"


@pytest.mark.asyncio
async def test_app_creates_chatbot_overrides_for_deployment_and_reasoning_only_differences(monkeypatch, minimal_env):
    monkeypatch.setenv("AZURE_SERVER_APP_SECRET", "test-server-secret")
    monkeypatch.setattr(
        app,
        "load_all_chatbot_configs",
        lambda: {
            "deploy-only": ChatbotConfig(name="deploy-only", chatgpt_deployment="bot-deploy"),
            "reasoning-only": ChatbotConfig(name="reasoning-only", reasoning_effort="low"),
            "same-as-default": ChatbotConfig(name="same-as-default"),
        },
    )

    quart_app = app.create_app()

    async with quart_app.test_app():
        chatbot_approaches = quart_app.config[app.CONFIG_CHATBOT_CHAT_APPROACHES]

        assert set(chatbot_approaches.keys()) == {"deploy-only", "reasoning-only"}
        assert chatbot_approaches["deploy-only"].chatgpt_model == "gpt-4.1-mini"
        assert chatbot_approaches["deploy-only"].chatgpt_deployment == "bot-deploy"
        assert chatbot_approaches["reasoning-only"].chatgpt_model == "gpt-4.1-mini"
        assert chatbot_approaches["reasoning-only"].chatgpt_deployment == "test-chat-deployment"
        assert chatbot_approaches["reasoning-only"].reasoning_effort == "low"


def test_app_enables_azure_monitor_when_connection_string_set(monkeypatch):
    mock_connection_string = "InstrumentationKey=12345678-1234-1234-1234-123456789012"
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", mock_connection_string)
    app.create_app()


def test_app_standalone_openlit_disables_non_llm_instrumentation(monkeypatch, minimal_env):
    monkeypatch.setenv("OPENLIT_ENDPOINT", "http://openlit.internal")

    openlit_init = mock.Mock()
    aiohttp_instrumentor = mock.Mock()
    httpx_instrumentor = mock.Mock()
    middleware = mock.Mock(side_effect=lambda asgi_app: asgi_app)

    monkeypatch.setitem(sys.modules, "openlit", mock.Mock(init=openlit_init))
    monkeypatch.setattr(app, "AioHttpClientInstrumentor", mock.Mock(return_value=aiohttp_instrumentor))
    monkeypatch.setattr(app, "HTTPXClientInstrumentor", mock.Mock(return_value=httpx_instrumentor))
    monkeypatch.setattr(app, "OpenTelemetryMiddleware", middleware)

    app.create_app()

    openlit_init.assert_called_once_with(
        otlp_endpoint="http://openlit.internal",
        application_name="azure-search-openai-demo",
        environment="production",
        disabled_instrumentors=app.get_openlit_llm_only_disabled_instrumentors(),
    )
    aiohttp_instrumentor.instrument.assert_not_called()
    httpx_instrumentor.instrument.assert_not_called()
    middleware.assert_not_called()


def test_app_openlit_dual_export_uses_llm_only_disabled_instrumentors(monkeypatch, minimal_env):
    class FakeTracerProvider(app.SDKTracerProvider):
        def __init__(self):
            super().__init__()
            self.added_span_processors = []

        def add_span_processor(self, span_processor):
            self.added_span_processors.append(span_processor)

    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=12345678-1234-1234-1234-123456789012"
    )
    monkeypatch.setenv("OPENLIT_ENDPOINT", "http://openlit.internal")

    provider = FakeTracerProvider()
    openlit_init = mock.Mock()
    aiohttp_instrumentor = mock.Mock()
    httpx_instrumentor = mock.Mock()
    middleware = mock.Mock(side_effect=lambda asgi_app: asgi_app)
    fake_exporter = object()
    fake_processor = object()

    monkeypatch.setitem(sys.modules, "openlit", mock.Mock(init=openlit_init))
    monkeypatch.setattr(app, "configure_azure_monitor", mock.Mock())
    monkeypatch.setattr(app.trace, "get_tracer_provider", mock.Mock(return_value=provider))
    monkeypatch.setattr(app, "OTLPSpanExporter", mock.Mock(return_value=fake_exporter))
    monkeypatch.setattr(app, "BatchSpanProcessor", mock.Mock(return_value=fake_processor))
    monkeypatch.setattr(app, "AioHttpClientInstrumentor", mock.Mock(return_value=aiohttp_instrumentor))
    monkeypatch.setattr(app, "HTTPXClientInstrumentor", mock.Mock(return_value=httpx_instrumentor))
    monkeypatch.setattr(app, "OpenTelemetryMiddleware", middleware)

    app.create_app()

    openlit_init.assert_called_once_with(
        otlp_endpoint="http://openlit.internal",
        application_name="azure-search-openai-demo",
        environment="production",
        disabled_instrumentors=app.get_openlit_llm_only_disabled_instrumentors(),
    )
    aiohttp_instrumentor.instrument.assert_called_once_with()
    httpx_instrumentor.instrument.assert_called_once_with()
    middleware.assert_called_once()
    assert provider.added_span_processors == [fake_processor]
    llm_exporter = app.BatchSpanProcessor.call_args.args[0]
    assert isinstance(llm_exporter, app.LLMOnlySpanExporter)
    assert llm_exporter._inner is fake_exporter
