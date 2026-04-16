import os
import time
from typing import Any

from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.identity.aio import AzureDeveloperCliCredential, ManagedIdentityCredential
from quart import Blueprint, current_app, jsonify, make_response, request

from approaches.chatbot_prompt_registry import normalize_chatbot_name
from config import (
    CONFIG_CHAT_HISTORY_COSMOS_ENABLED,
    CONFIG_COSMOS_HISTORY_CLIENT,
    CONFIG_COSMOS_HISTORY_CONTAINER,
    CONFIG_COSMOS_HISTORY_VERSION,
    CONFIG_CREDENTIAL,
    CONFIG_PUBLIC_TEST_AUTH_SERVICE,
)
from core.publictestauth import PublicTestAuthStore
from decorators import authenticated
from error import error_response

chat_history_cosmosdb_bp = Blueprint("chat_history_cosmos", __name__, static_folder="static")

PUBLIC_TEST_CHATBOT_NAME = "public-test"
PUBLIC_TEST_HISTORY_USER_PREFIX = "public-test:"
RAK_CHATBOT_NAME = "rak"
RAK_HISTORY_USER_PREFIX = "rak:"
RAK_ALLOWED_USERNAMES = {"12345", "67890"}


def normalize_rak_history_username(raw_username: str | None) -> str | None:
    normalized_username = (raw_username or "").strip()
    if not normalized_username:
        return None

    return normalized_username if normalized_username in RAK_ALLOWED_USERNAMES else None


async def resolve_history_user_id(chatbot_name: str, auth_claims: dict[str, Any]) -> str | None:
    chatbot_name = normalize_chatbot_name(chatbot_name) or chatbot_name.strip().lower()
    if chatbot_name == PUBLIC_TEST_CHATBOT_NAME:
        auth_service = current_app.config.get(CONFIG_PUBLIC_TEST_AUTH_SERVICE)
        if auth_service is None:
            return None

        public_test_auth_service = auth_service
        session = await public_test_auth_service.load_session(
            request.cookies.get(public_test_auth_service.session_cookie_name)
        )
        if session is None:
            return None

        return f"{PUBLIC_TEST_HISTORY_USER_PREFIX}{PublicTestAuthStore.hash_email(session.email)}"

    if chatbot_name == RAK_CHATBOT_NAME:
        rak_username = normalize_rak_history_username(request.headers.get("X-Chatbot-User"))
        if rak_username is None:
            rak_username = normalize_rak_history_username(request.args.get("chatbot_user"))
        return f"{RAK_HISTORY_USER_PREFIX}{rak_username}" if rak_username is not None else None

    entra_oid = auth_claims.get("oid")
    return str(entra_oid) if entra_oid else None


@chat_history_cosmosdb_bp.post("/chat_history")
@authenticated
async def post_chat_history(auth_claims: dict[str, Any]):
    if not current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED]:
        return jsonify({"error": "Chat history not enabled"}), 400

    container: ContainerProxy = current_app.config[CONFIG_COSMOS_HISTORY_CONTAINER]
    if not container:
        return jsonify({"error": "Chat history not enabled"}), 400

    try:
        request_json = await request.get_json()
        session_id = request_json.get("id")
        message_pairs = request_json.get("answers")
        chatbot_name = normalize_chatbot_name(request_json.get("chatbot_name")) or ""
        history_user_id = await resolve_history_user_id(chatbot_name, auth_claims)
        if not history_user_id:
            return jsonify({"error": "User history scope not found"}), 401
        first_question = message_pairs[0][0]
        title = first_question + "..." if len(first_question) > 50 else first_question
        timestamp = int(time.time() * 1000)

        # Insert the session item:
        session_item = {
            "id": session_id,
            "version": current_app.config[CONFIG_COSMOS_HISTORY_VERSION],
            "session_id": session_id,
            "entra_oid": history_user_id,
            "chatbot_name": chatbot_name,
            "type": "session",
            "title": title,
            "timestamp": timestamp,
        }

        message_pair_items = []
        # Now insert a message item for each question/response pair:
        for ind, message_pair in enumerate(message_pairs):
            message_pair_items.append(
                {
                    "id": f"{session_id}-{ind}",
                    "version": current_app.config[CONFIG_COSMOS_HISTORY_VERSION],
                    "session_id": session_id,
                    "entra_oid": history_user_id,
                    "chatbot_name": chatbot_name,
                    "type": "message_pair",
                    "question": message_pair[0],
                    "response": message_pair[1],
                }
            )

        batch_operations = [("upsert", (session_item,))] + [
            ("upsert", (message_pair_item,)) for message_pair_item in message_pair_items
        ]
        await container.execute_item_batch(batch_operations=batch_operations, partition_key=[history_user_id, session_id])
        return jsonify({}), 201
    except Exception as error:
        return error_response(error, "/chat_history")


@chat_history_cosmosdb_bp.get("/chat_history/sessions")
@authenticated
async def get_chat_history_sessions(auth_claims: dict[str, Any]):
    if not current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED]:
        return jsonify({"error": "Chat history not enabled"}), 400

    container: ContainerProxy = current_app.config[CONFIG_COSMOS_HISTORY_CONTAINER]
    if not container:
        return jsonify({"error": "Chat history not enabled"}), 400

    try:
        count = int(request.args.get("count", 10))
        continuation_token = request.args.get("continuation_token")
        chatbot_name = normalize_chatbot_name(request.args.get("chatbot_name")) or ""
        history_user_id = await resolve_history_user_id(chatbot_name, auth_claims)
        if not history_user_id:
            return jsonify({"error": "User history scope not found"}), 401

        res = container.query_items(
            query="SELECT c.id, c.entra_oid, c.title, c.timestamp FROM c WHERE c.entra_oid = @entra_oid AND c.type = @type AND c.chatbot_name = @chatbot_name ORDER BY c.timestamp DESC",
            parameters=[
                dict(name="@entra_oid", value=history_user_id),
                dict(name="@type", value="session"),
                dict(name="@chatbot_name", value=chatbot_name),
            ],
            partition_key=[history_user_id],
            max_item_count=count,
        )

        pager = res.by_page(continuation_token)

        # Get the first page, and the continuation token
        sessions = []
        try:
            page = await pager.__anext__()
            continuation_token = pager.continuation_token

            async for item in page:
                sessions.append(
                    {
                        "id": item.get("id"),
                        "entra_oid": item.get("entra_oid"),
                        "title": item.get("title", "untitled"),
                        "timestamp": item.get("timestamp"),
                    }
                )

        # If there are no more pages, StopAsyncIteration is raised
        except StopAsyncIteration:
            continuation_token = None

        return jsonify({"sessions": sessions, "continuation_token": continuation_token}), 200

    except Exception as error:
        return error_response(error, "/chat_history/sessions")


@chat_history_cosmosdb_bp.get("/chat_history/sessions/<session_id>")
@authenticated
async def get_chat_history_session(auth_claims: dict[str, Any], session_id: str):
    if not current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED]:
        return jsonify({"error": "Chat history not enabled"}), 400

    container: ContainerProxy = current_app.config[CONFIG_COSMOS_HISTORY_CONTAINER]
    if not container:
        return jsonify({"error": "Chat history not enabled"}), 400

    try:
        chatbot_name = normalize_chatbot_name(request.args.get("chatbot_name")) or ""
        history_user_id = await resolve_history_user_id(chatbot_name, auth_claims)
        if not history_user_id:
            return jsonify({"error": "User history scope not found"}), 401
        res = container.query_items(
            query="SELECT * FROM c WHERE c.session_id = @session_id AND c.type = @type AND c.chatbot_name = @chatbot_name",
            parameters=[
                dict(name="@session_id", value=session_id),
                dict(name="@type", value="message_pair"),
                dict(name="@chatbot_name", value=chatbot_name),
            ],
            partition_key=[history_user_id, session_id],
        )

        message_pairs = []
        async for page in res.by_page():
            async for item in page:
                message_pairs.append([item["question"], item["response"]])

        return (
            jsonify(
                {
                    "id": session_id,
                    "entra_oid": history_user_id,
                    "answers": message_pairs,
                }
            ),
            200,
        )
    except Exception as error:
        return error_response(error, f"/chat_history/sessions/{session_id}")


@chat_history_cosmosdb_bp.delete("/chat_history/sessions/<session_id>")
@authenticated
async def delete_chat_history_session(auth_claims: dict[str, Any], session_id: str):
    if not current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED]:
        return jsonify({"error": "Chat history not enabled"}), 400

    container: ContainerProxy = current_app.config[CONFIG_COSMOS_HISTORY_CONTAINER]
    if not container:
        return jsonify({"error": "Chat history not enabled"}), 400

    try:
        chatbot_name = normalize_chatbot_name(request.args.get("chatbot_name")) or ""
        history_user_id = await resolve_history_user_id(chatbot_name, auth_claims)
        if not history_user_id:
            return jsonify({"error": "User history scope not found"}), 401
        res = container.query_items(
            query="SELECT c.id FROM c WHERE c.session_id = @session_id AND c.chatbot_name = @chatbot_name",
            parameters=[dict(name="@session_id", value=session_id), dict(name="@chatbot_name", value=chatbot_name)],
            partition_key=[history_user_id, session_id],
        )

        ids_to_delete = []
        async for page in res.by_page():
            async for item in page:
                ids_to_delete.append(item["id"])

        batch_operations = [("delete", (id,)) for id in ids_to_delete]
        await container.execute_item_batch(batch_operations=batch_operations, partition_key=[history_user_id, session_id])
        return await make_response("", 204)
    except Exception as error:
        return error_response(error, f"/chat_history/sessions/{session_id}")


@chat_history_cosmosdb_bp.before_app_serving
async def setup_clients():
    USE_CHAT_HISTORY_COSMOS = os.getenv("USE_CHAT_HISTORY_COSMOS", "").lower() == "true"
    AZURE_COSMOSDB_ACCOUNT = os.getenv("AZURE_COSMOSDB_ACCOUNT")
    AZURE_CHAT_HISTORY_DATABASE = os.getenv("AZURE_CHAT_HISTORY_DATABASE")
    AZURE_CHAT_HISTORY_CONTAINER = os.getenv("AZURE_CHAT_HISTORY_CONTAINER")

    azure_credential: AzureDeveloperCliCredential | ManagedIdentityCredential = current_app.config[CONFIG_CREDENTIAL]

    if USE_CHAT_HISTORY_COSMOS:
        current_app.logger.info("USE_CHAT_HISTORY_COSMOS is true, setting up CosmosDB client")
        if not AZURE_COSMOSDB_ACCOUNT:
            raise ValueError("AZURE_COSMOSDB_ACCOUNT must be set when USE_CHAT_HISTORY_COSMOS is true")
        if not AZURE_CHAT_HISTORY_DATABASE:
            raise ValueError("AZURE_CHAT_HISTORY_DATABASE must be set when USE_CHAT_HISTORY_COSMOS is true")
        if not AZURE_CHAT_HISTORY_CONTAINER:
            raise ValueError("AZURE_CHAT_HISTORY_CONTAINER must be set when USE_CHAT_HISTORY_COSMOS is true")
        cosmos_client = CosmosClient(
            url=f"https://{AZURE_COSMOSDB_ACCOUNT}.documents.azure.com:443/", credential=azure_credential
        )
        cosmos_db = cosmos_client.get_database_client(AZURE_CHAT_HISTORY_DATABASE)
        cosmos_container = cosmos_db.get_container_client(AZURE_CHAT_HISTORY_CONTAINER)

        current_app.config[CONFIG_COSMOS_HISTORY_CLIENT] = cosmos_client
        current_app.config[CONFIG_COSMOS_HISTORY_CONTAINER] = cosmos_container
        current_app.config[CONFIG_COSMOS_HISTORY_VERSION] = os.environ["AZURE_CHAT_HISTORY_VERSION"]


@chat_history_cosmosdb_bp.after_app_serving
async def close_clients():
    if current_app.config.get(CONFIG_COSMOS_HISTORY_CLIENT):
        cosmos_client: CosmosClient = current_app.config[CONFIG_COSMOS_HISTORY_CLIENT]
        await cosmos_client.close()
