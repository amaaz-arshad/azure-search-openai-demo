import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path


logger = logging.getLogger("scripts")

FUNCTION_TRIGGER_POLL_TIMEOUT_SECONDS = 180
FUNCTION_TRIGGER_POLL_INTERVAL_SECONDS = 5
SUBSCRIPTIONS = (
    {
        "name": "moodle-auto-indexer-create-sync",
        "function_name": "moodle_auto_index",
        "event_types": ("Microsoft.Storage.BlobCreated",),
        "description": "Moodle create/update",
        "subject_prefix": "/blobServices/default/containers/content/blobs/nerilio/Nerilio-Moodle/",
        "subject_suffix": ".xml",
    },
    {
        "name": "moodle-auto-indexer-delete-sync",
        "function_name": "moodle_delete_sync",
        "event_types": ("Microsoft.Storage.BlobDeleted",),
        "description": "Moodle delete-sync",
        "subject_prefix": "/blobServices/default/containers/content/blobs/nerilio/Nerilio-Moodle/",
        "subject_suffix": ".xml",
    },
    {
        "name": "publishone-auto-indexer-create-sync",
        "function_name": "publishone_auto_index",
        "event_types": ("Microsoft.Storage.BlobCreated",),
        "description": "PublishOne create/update",
        "subject_prefix": "/blobServices/default/containers/content/blobs/nerilio/Nerilio-PublishOne/",
        "subject_suffix": ".xml",
    },
    {
        "name": "publishone-auto-indexer-delete-sync",
        "function_name": "publishone_delete_sync",
        "event_types": ("Microsoft.Storage.BlobDeleted",),
        "description": "PublishOne delete-sync",
        "subject_prefix": "/blobServices/default/containers/content/blobs/nerilio/Nerilio-PublishOne/",
        "subject_suffix": ".xml",
    },
    {
        "name": "fhg-auto-indexer-create-sync",
        "function_name": "fhg_auto_index",
        "event_types": ("Microsoft.Storage.BlobCreated",),
        "description": "FHG create/update",
        "subject_prefix": "/blobServices/default/containers/content/blobs/nerilio/Nerilio-fhg/",
        "subject_suffix": ".json",
    },
    {
        "name": "fhg-auto-indexer-delete-sync",
        "function_name": "fhg_delete_sync",
        "event_types": ("Microsoft.Storage.BlobDeleted",),
        "description": "FHG delete-sync",
        "subject_prefix": "/blobServices/default/containers/content/blobs/nerilio/Nerilio-fhg/",
        "subject_suffix": ".json",
    },
    {
        # content2 dynamic multi-bot indexer: watches the whole content2 container so any new
        # bot folder (content2/<bot_name>/) is covered without a new subscription. No suffix
        # filter — many extensions are supported; the function's is_supported() gate filters.
        "name": "content2-auto-indexer-create-sync",
        "function_name": "content2_auto_index",
        "event_types": ("Microsoft.Storage.BlobCreated",),
        "description": "content2 create/update",
        "subject_prefix": "/blobServices/default/containers/content2/blobs/",
        "subject_suffix": "",
    },
    {
        "name": "content2-auto-indexer-delete-sync",
        "function_name": "content2_delete_sync",
        "event_types": ("Microsoft.Storage.BlobDeleted",),
        "description": "content2 delete-sync",
        "subject_prefix": "/blobServices/default/containers/content2/blobs/",
        "subject_suffix": "",
    },
)


def resolve_cli_executable(*candidates: str) -> str:
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise FileNotFoundError(f"Unable to find any of these executables in PATH: {', '.join(candidates)}")


def run_cli(command: list[str]) -> subprocess.CompletedProcess[str]:
    logger.debug("Running command: %s", " ".join(command))
    return subprocess.run(command, check=False, capture_output=True, text=True)


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Environment variable '{name}' is required.")
    return value


def load_default_azd_env() -> None:
    azd_executable = resolve_cli_executable("azd.cmd", "azd.exe", "azd")
    result = run_cli([azd_executable, "env", "list", "-o", "json"])
    if result.returncode != 0:
        raise RuntimeError(f"Unable to list azd environments.\n{result.stderr.strip()}")

    environments = json.loads(result.stdout or "[]")
    dotenv_path = None
    for entry in environments:
        if entry.get("IsDefault"):
            dotenv_path = entry.get("DotEnvPath")
            break

    if not dotenv_path:
        raise RuntimeError("Unable to find the default azd environment.")

    env_path = Path(dotenv_path)
    if not env_path.exists():
        raise RuntimeError(f"Default azd environment file not found: {env_path}")

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_function_app_name(resource_group: str) -> str:
    az_executable = resolve_cli_executable("az.cmd", "az.exe", "az")
    result = run_cli(
        [
            az_executable,
            "resource",
            "list",
            "--resource-group",
            resource_group,
            "-o",
            "json",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to resolve moodle-auto-indexer Function App.\n{result.stderr.strip()}")

    resources = json.loads(result.stdout or "[]")
    function_app_name = ""
    for resource in resources:
        if resource.get("type") != "Microsoft.Web/sites":
            continue
        tags = resource.get("tags") or {}
        if tags.get("azd-service-name") == "moodle-auto-indexer":
            function_app_name = str(resource.get("name") or "").strip()
            break
    if not function_app_name:
        raise RuntimeError("No Function App tagged with azd-service-name=moodle-auto-indexer was found.")
    return function_app_name


def event_subscription_exists(source_resource_id: str, subscription_name: str) -> bool:
    az_executable = resolve_cli_executable("az.cmd", "az.exe", "az")
    result = run_cli(
        [
            az_executable,
            "eventgrid",
            "event-subscription",
            "show",
            "--source-resource-id",
            source_resource_id,
            "--name",
            subscription_name,
            "-o",
            "none",
        ]
    )
    return result.returncode == 0


def resolve_function_trigger_types(resource_group: str, function_app_name: str) -> dict[str, list[str]]:
    az_executable = resolve_cli_executable("az.cmd", "az.exe", "az")
    result = run_cli(
        [
            az_executable,
            "functionapp",
            "function",
            "list",
            "--resource-group",
            resource_group,
            "--name",
            function_app_name,
            "-o",
            "json",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to list functions for Function App '{function_app_name}'.\n{result.stderr.strip()}")

    functions = json.loads(result.stdout or "[]")
    trigger_types: dict[str, list[str]] = {}
    for function in functions:
        function_name = str(((function.get("config") or {}).get("name")) or "").strip()
        bindings = ((function.get("config") or {}).get("bindings")) or []
        trigger_types[function_name] = [str(binding.get("type") or "") for binding in bindings if binding.get("direction") == "IN"]
    return trigger_types


def wait_for_event_grid_trigger(resource_group: str, function_app_name: str, function_name: str) -> None:
    deadline = time.time() + FUNCTION_TRIGGER_POLL_TIMEOUT_SECONDS
    last_trigger_types: list[str] = []

    while time.time() < deadline:
        trigger_types_by_function = resolve_function_trigger_types(resource_group, function_app_name)
        last_trigger_types = trigger_types_by_function.get(function_name, [])
        if "eventGridTrigger" in last_trigger_types:
            return
        time.sleep(FUNCTION_TRIGGER_POLL_INTERVAL_SECONDS)

    rendered_trigger_types = ", ".join(last_trigger_types) if last_trigger_types else "<missing>"
    raise RuntimeError(
        f"Function '{function_name}' on app '{function_app_name}' did not become an eventGridTrigger within "
        f"{FUNCTION_TRIGGER_POLL_TIMEOUT_SECONDS} seconds. Last seen input trigger types: {rendered_trigger_types}"
    )


def configure_single_subscription(
    *,
    subscription_id: str,
    resource_group: str,
    storage_resource_group: str,
    storage_account: str,
    function_app_name: str,
    subscription_name: str,
    function_name: str,
    event_types: tuple[str, ...],
    description: str,
    subject_prefix: str,
    subject_suffix: str,
) -> None:
    source_resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{storage_resource_group}"
        f"/providers/Microsoft.Storage/storageAccounts/{storage_account}"
    )
    function_resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Web/sites/{function_app_name}/functions/{function_name}"
    )
    az_executable = resolve_cli_executable("az.cmd", "az.exe", "az")
    wait_for_event_grid_trigger(resource_group, function_app_name, function_name)
    subscription_exists = event_subscription_exists(source_resource_id, subscription_name)

    command = [
        az_executable,
        "eventgrid",
        "event-subscription",
        "update" if subscription_exists else "create",
        "--name",
        subscription_name,
        "--source-resource-id",
        source_resource_id,
        "--endpoint-type",
        "azurefunction",
        "--endpoint",
        function_resource_id,
        "--subject-begins-with",
        subject_prefix,
        "-o",
        "none",
    ]
    if subject_suffix:
        command.extend(["--subject-ends-with", subject_suffix])
    if event_types:
        command.extend(["--included-event-types", *event_types])
    if not subscription_exists:
        command.extend(["--event-delivery-schema", "eventgridschema"])

    result = run_cli(command)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to configure {description} event subscription.\n{result.stderr.strip()}")

    logger.info(
        "Configured Event Grid %s subscription '%s' on storage account '%s' for Function App '%s'.",
        description,
        subscription_name,
        storage_account,
        function_app_name,
    )


def configure_event_subscription() -> None:
    required_env_names = (
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_RESOURCE_GROUP",
        "AZURE_STORAGE_RESOURCE_GROUP",
        "AZURE_STORAGE_ACCOUNT",
    )
    if not all(os.getenv(name, "").strip() for name in required_env_names):
        load_default_azd_env()

    subscription_id = required_env("AZURE_SUBSCRIPTION_ID")
    resource_group = required_env("AZURE_RESOURCE_GROUP")
    storage_resource_group = required_env("AZURE_STORAGE_RESOURCE_GROUP")
    storage_account = required_env("AZURE_STORAGE_ACCOUNT")

    function_app_name = resolve_function_app_name(resource_group)
    for subscription in SUBSCRIPTIONS:
        configure_single_subscription(
            subscription_id=subscription_id,
            resource_group=resource_group,
            storage_resource_group=storage_resource_group,
            storage_account=storage_account,
            function_app_name=function_app_name,
            subscription_name=subscription["name"],
            function_name=subscription["function_name"],
            event_types=subscription["event_types"],
            description=subscription["description"],
            subject_prefix=subscription["subject_prefix"],
            subject_suffix=subscription["subject_suffix"],
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    configure_event_subscription()
