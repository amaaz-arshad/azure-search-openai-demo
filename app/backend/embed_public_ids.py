"""Anonymous public identifiers for the embeddable chatbot widget.

The widget embed code references a chatbot by an opaque, generated public ID (GA/Clarity style,
e.g. ``muw0oowcw3``) instead of its readable route name. This keeps the chatbot name out of the
host page DOM and the iframe ``src``. The mapping is committed here so embed codes are stable
across deploys; the editable per-bot whitelist lives in the blob-backed ChatbotEmbedConfigStore.

Only the public ID is exposed for widget integration. The internal route names stay unchanged and
remain how the app is browsed directly (``/<chatbot_name>``) and administered.

TWO SOURCES, ONE ID SPACE. Built-in bots get their IDs from the committed ``EMBED_PUBLIC_IDS``
map below (add one with ``python -m embed_public_ids``, then paste and commit). Dynamic
(provisioned) bots get theirs minted at create time and stored on their registry record
(``ChatbotRegistryRecord.embed_public_id``), because there is no source file to commit for a bot
the control panel invents at runtime. Minting checks both sets, so the ID space stays 1:1 and a
dynamic bot can never collide with a built-in. Resolution follows the same order: the committed
map first (no I/O, so built-in embeds never depend on the registry), then the registry.
"""

import asyncio
import logging
import re
import secrets
import string
import time
from collections.abc import Mapping
from typing import Optional, Protocol

from approaches.chatbot_prompt_registry import get_registered_chatbot_names, normalize_chatbot_name

logger = logging.getLogger(__name__)

# Stable, generated public IDs. Keys are canonical chatbot route names (post-alias, so "free" not
# "public-test"). Do not edit existing values — changing one breaks every embed already in the wild.
EMBED_PUBLIC_IDS: dict[str, str] = {
    "agindo": "l43xvr1plu",
    "bbsa": "ibu732n0pa",
    "bensberg": "bq6z8n2lad",
    "nerilio": "skmhmm4vzl",
    "free": "vlx3ztxsca",
    "rak": "nk0liu1lzo",
    "sartorius": "x9uqlmnq8o",
    "steuertipps": "n7z52lzjfy",
    "knoll": "itlb61imga",
    "lemon": "hzda0mvocb",
    "hyrox-assessment": "by7ewngt4w",
    "moodle": "qrwok2uqyr",
    "publishone": "oba6k03jtq",
    "publishone2": "mj28aprop3",
    "fbn": "i9aa3rnmjn",
    "demo": "vwc2zfkvbj",
    "fhg": "b8krfl2e9a",
    "vjoonk4": "kwulio1p0i",
    "snap": "r54q95959d",
    "cbtx": "xtiz6o38j6",
}

PUBLIC_ID_LENGTH = 10
PUBLIC_ID_ALPHABET = string.ascii_lowercase + string.digits
# Every minted ID has this exact shape. Checked before any registry lookup so a malformed or
# probed value costs zero I/O (see resolve_public_id_async).
PUBLIC_ID_RE = re.compile(r"^[a-z][a-z0-9]{%d}$" % (PUBLIC_ID_LENGTH - 1))

# Reverse lookup built once at import. Both directions are 1:1.
PUBLIC_ID_TO_CHATBOT: dict[str, str] = {public_id: name for name, public_id in EMBED_PUBLIC_IDS.items()}


def get_public_id(chatbot_name: Optional[str]) -> Optional[str]:
    """Return the committed public ID for a BUILT-IN chatbot route name, or None.

    Dynamic bots are not in the committed map — their ID lives on the registry record, so use
    ``get_record_public_id`` / ``resolve_public_id_async`` for them.
    """
    normalized = normalize_chatbot_name(chatbot_name)
    if normalized is None:
        return None
    return EMBED_PUBLIC_IDS.get(normalized)


def resolve_public_id(public_id: Optional[str]) -> Optional[str]:
    """Return the canonical BUILT-IN chatbot route name for a public ID, or None if unknown.

    Synchronous and I/O-free; it only sees the committed map. Routes that must also serve dynamic
    bots use ``resolve_public_id_async``.
    """
    if not public_id:
        return None
    return PUBLIC_ID_TO_CHATBOT.get(public_id.strip())


def is_embeddable(chatbot_name: Optional[str]) -> bool:
    """A BUILT-IN chatbot is embeddable iff it has a committed public ID.

    Dynamic bots are embeddable by virtue of existing in the registry; ``app.is_embeddable_chatbot``
    is the combined check used by the admin endpoints.
    """
    return get_public_id(chatbot_name) is not None


def looks_like_public_id(value: Optional[str]) -> bool:
    """True if ``value`` has the shape of a minted public ID (cheap pre-check, no lookup)."""
    return bool(value) and PUBLIC_ID_RE.match(value.strip()) is not None  # type: ignore[union-attr]


def build_embed_snippet(origin: str, public_id: str) -> str:
    """The one-line <script> tag a site owner pastes to embed a bot.

    Kept here so the provisioning API response, the admin Embed modal, and the embed-demo page all
    describe the same snippet.
    """
    return f'<script async src="{origin.rstrip("/")}/widget.js" data-chatbot-id="{public_id}"></script>'


def generate_public_id(taken: Optional[set[str]] = None) -> str:
    """Generate a fresh, non-readable public ID that collides with nothing.

    Starts with a letter (GA/Clarity style) so it is never all-numeric. ``taken`` carries the IDs
    already handed out to dynamic bots; the committed built-in map is always excluded.
    """
    reserved = set(PUBLIC_ID_TO_CHATBOT)
    if taken:
        reserved |= taken
    while True:
        candidate = secrets.choice(string.ascii_lowercase) + "".join(
            secrets.choice(PUBLIC_ID_ALPHABET) for _ in range(PUBLIC_ID_LENGTH - 1)
        )
        if candidate not in reserved:
            return candidate


class RegistryRecordLike(Protocol):
    """The two fields the public-ID layer needs from a registry record."""

    bot_name: str
    embed_public_id: Optional[str]


class RegistryStoreLike(Protocol):
    """The single registry method the public-ID layer needs.

    Returns a Mapping rather than a dict so a concrete ``dict[str, ChatbotRegistryRecord]`` satisfies
    it — dict is invariant in its value type, Mapping is covariant.
    """

    async def list_records(self) -> Mapping[str, RegistryRecordLike]: ...


def get_record_public_id(record: Optional[RegistryRecordLike]) -> Optional[str]:
    """Return a dynamic record's stored public ID, or None when it has not been minted yet."""
    if record is None:
        return None
    public_id = getattr(record, "embed_public_id", None)
    return public_id if isinstance(public_id, str) and public_id else None


class DynamicPublicIdIndex:
    """In-process publicId -> botName index for dynamic bots.

    A pure cache over the registry (records stay the source of truth), so it cannot drift: a miss
    rescans, and the scan is rate-limited by ``min_refresh_interval`` so a flood of unknown IDs
    cannot turn into a flood of blob listings. Entries are keyed on the ID only, independent of the
    bot's active flag — start/stop therefore needs no invalidation, and callers check ``active``
    themselves (a stopped bot resolves by ID but must not be served).
    """

    def __init__(self, min_refresh_interval: float = 5.0):
        self.by_public_id: dict[str, str] = {}
        self.min_refresh_interval = min_refresh_interval
        self.last_refresh: Optional[float] = None
        self.refresh_lock = asyncio.Lock()

    def remember(self, public_id: Optional[str], bot_name: Optional[str]) -> None:
        """Seed a freshly minted ID so it resolves immediately, without waiting for a refresh."""
        if public_id and bot_name:
            self.by_public_id[public_id] = bot_name

    def forget_bot(self, bot_name: Optional[str]) -> None:
        """Drop every entry for a bot (called when it is deleted)."""
        if not bot_name:
            return
        for public_id in [pid for pid, name in self.by_public_id.items() if name == bot_name]:
            self.by_public_id.pop(public_id, None)

    def may_refresh(self) -> bool:
        if self.last_refresh is None:
            return True
        return (time.monotonic() - self.last_refresh) >= self.min_refresh_interval

    async def refresh(self, store: RegistryStoreLike) -> None:
        async with self.refresh_lock:
            # Another task may have refreshed while we waited for the lock.
            if not self.may_refresh():
                return
            records = await store.list_records()
            self.by_public_id = {
                public_id: record.bot_name
                for record in records.values()
                if (public_id := get_record_public_id(record)) is not None
            }
            self.last_refresh = time.monotonic()

    async def resolve(self, public_id: str, store: RegistryStoreLike) -> Optional[str]:
        hit = self.by_public_id.get(public_id)
        if hit is not None:
            return hit
        if not self.may_refresh():
            return None
        try:
            await self.refresh(store)
        except Exception:
            # The widget/iframe path must never 500 because the registry is briefly unreachable.
            logger.exception("Failed to refresh the dynamic embed public-ID index")
            return None
        return self.by_public_id.get(public_id)


# Module-level cache; the registry blobs remain the source of truth (see DynamicPublicIdIndex).
DYNAMIC_PUBLIC_ID_INDEX = DynamicPublicIdIndex()


async def resolve_public_id_async(public_id: Optional[str], store: Optional[RegistryStoreLike]) -> Optional[str]:
    """Resolve a public ID to a chatbot route name across BOTH built-in and dynamic bots.

    Built-in IDs resolve from the committed map with no I/O. Anything else must look like a minted
    ID before the registry is consulted, so probes and malformed values are rejected for free.
    Returns a name only — callers still enforce the bot's own gates (a stopped dynamic bot
    resolves here but must not be served).
    """
    normalized = public_id.strip() if isinstance(public_id, str) else ""
    builtin_name = resolve_public_id(normalized)
    if builtin_name is not None:
        return builtin_name
    if store is None or not looks_like_public_id(normalized):
        return None
    return await DYNAMIC_PUBLIC_ID_INDEX.resolve(normalized, store)


async def mint_public_id(store: RegistryStoreLike) -> str:
    """Mint a public ID for a new dynamic bot, avoiding every ID already in use.

    Scans the registry so the check covers IDs minted by other replicas. On a scan failure it still
    returns an ID (checked against the committed built-in map and the local index) rather than
    failing the provisioning call — a 1-in-36^9 collision is a far smaller risk than a create that
    cannot complete because blob storage hiccuped.
    """
    taken = set(DYNAMIC_PUBLIC_ID_INDEX.by_public_id)
    try:
        records = await store.list_records()
        taken |= {
            public_id for record in records.values() if (public_id := get_record_public_id(record)) is not None
        }
    except Exception:
        logger.exception("Could not list the chatbot registry while minting an embed public ID")
    return generate_public_id(taken)


def main() -> None:
    """Print suggested EMBED_PUBLIC_IDS lines for any embeddable bot that is missing one."""
    missing = [name for name in get_registered_chatbot_names() if name not in EMBED_PUBLIC_IDS]
    if not missing:
        print("All embeddable chatbots already have a public ID.")
        return
    print("# Add these lines to EMBED_PUBLIC_IDS in embed_public_ids.py:")
    for name in missing:
        print(f'    "{name}": "{generate_public_id()}",')


if __name__ == "__main__":
    main()
