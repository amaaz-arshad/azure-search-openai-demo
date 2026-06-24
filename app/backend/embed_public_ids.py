"""Anonymous public identifiers for the embeddable chatbot widget.

The widget embed code references a chatbot by an opaque, generated public ID (GA/Clarity style,
e.g. ``muw0oowcw3``) instead of its readable route name. This keeps the chatbot name out of the
host page DOM and the iframe ``src``. The mapping is committed here so embed codes are stable
across deploys; the editable per-bot whitelist lives in the blob-backed ChatbotEmbedConfigStore.

Only the public ID is exposed for widget integration. The internal route names stay unchanged and
remain how the app is browsed directly (``/<chatbot_name>``) and administered.

Adding a chatbot: run ``python -m embed_public_ids`` to print suggested lines for any embeddable
bot missing an ID, then paste them into ``EMBED_PUBLIC_IDS`` below and commit.
"""

import secrets
import string
from typing import Optional

from approaches.chatbot_prompt_registry import get_registered_chatbot_names, normalize_chatbot_name

# Stable, generated public IDs. Keys are canonical chatbot route names (post-alias, so "free" not
# "public-test"). Do not edit existing values — changing one breaks every embed already in the wild.
EMBED_PUBLIC_IDS: dict[str, str] = {
    "agindo": "l43xvr1plu",
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
    "fbn": "i9aa3rnmjn",
    "demo": "vwc2zfkvbj",
    "fhg": "b8krfl2e9a",
    "vjoonk4": "kwulio1p0i",
    "snap": "r54q95959d",
}

PUBLIC_ID_LENGTH = 10
PUBLIC_ID_ALPHABET = string.ascii_lowercase + string.digits

# Reverse lookup built once at import. Both directions are 1:1.
PUBLIC_ID_TO_CHATBOT: dict[str, str] = {public_id: name for name, public_id in EMBED_PUBLIC_IDS.items()}


def get_public_id(chatbot_name: Optional[str]) -> Optional[str]:
    """Return the public ID for a chatbot route name, or None if it has no embed identity."""
    normalized = normalize_chatbot_name(chatbot_name)
    if normalized is None:
        return None
    return EMBED_PUBLIC_IDS.get(normalized)


def resolve_public_id(public_id: Optional[str]) -> Optional[str]:
    """Return the canonical chatbot route name for a public ID, or None if unknown."""
    if not public_id:
        return None
    return PUBLIC_ID_TO_CHATBOT.get(public_id.strip())


def is_embeddable(chatbot_name: Optional[str]) -> bool:
    """A chatbot is embeddable iff it has been assigned a public ID."""
    return get_public_id(chatbot_name) is not None


def generate_public_id() -> str:
    """Generate a fresh, non-readable public ID that does not collide with an existing one.

    Starts with a letter (GA/Clarity style) so it is never all-numeric.
    """
    while True:
        candidate = secrets.choice(string.ascii_lowercase) + "".join(
            secrets.choice(PUBLIC_ID_ALPHABET) for _ in range(PUBLIC_ID_LENGTH - 1)
        )
        if candidate not in PUBLIC_ID_TO_CHATBOT:
            return candidate


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
