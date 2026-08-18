"""XML dispatch for provisioned ("generic") chatbot knowledge bases.

The content2 dynamic indexer parses everything generically, which for ``.xml`` means
``XmlParser`` flattening the tree into `path: value` lines and letting the sentence splitter run
over the whole document. For a structured knowledge export that is as lossy as ``JsonParser`` was
for a JSON record collection: the live ``content2/hyroxlemon/`` file is a ``<knowledge>`` export of
755 chunks and became 4,784 documents with no title, no per-chunk boundary and no citation metadata.

The repo already has the right parser for that shape (``lemonxml``), it is simply gated on category
``lemon``. Rather than duplicate it, this module sniffs the root element and re-dispatches to the
existing parser with the provisioned bot's own category.

Two rules keep this safe for a customer's arbitrary XML:

  * **Sniff, then parse.** Nothing is claimed unless the root element matches a known shape, so an
    unrecognised document falls through to the generic parser exactly as before.
  * **A parse failure is a decline, not an error.** ``lemonxml`` validates strictly and raises
    ``ValueError`` on a duplicate chunk id or an empty ``<content>`` - correct for a first-party
    feed, wrong here, where a malformed customer file must not fail that bot's whole ingest. The
    exception is logged and the file falls back to the generic parser.
"""

import logging
import os
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from typing import Optional

from .lemonxml import is_lemon_knowledge_xml, load_xml_root, prepare_lemon_xml_sections
from .listfilestrategy import File
from .page import Chunk
from .searchmanager import Section

logger = logging.getLogger("scripts")

# Built from a codepoint rather than written as an escape, matching dynamicjson.py: this file is
# edited by tooling that does not reliably round-trip backslash escapes.
PARAGRAPH_BREAK = chr(10) * 2


def rebind_sections_for_dynamic_bot(sections: list[Section], *, sourcefile: str) -> list[Section]:
    """Adapt knowledge-XML sections to the content2 citation contract.

    Two adjustments, both needed because these sections are cited through ``/content2/<bot>/...``
    rather than through a first-party feed's external URL:

    * ``sourcepage`` becomes the source filename. ``lemonxml`` sets it to the chunk id, which is
      right for the lemon corpus (whose citations are the unit URL) but here would be the citation
      string itself, resolving to ``/content2/<bot>/c0001`` - a 404. The filename is the only value
      that resolves to a real blob, and it is what the generic parser already produced.
    * The unit/section title is prepended to the chunk body. ``lemonxml`` puts the unit title in the
      ``title`` field only, and the model is shown ``"<citation>: <content>"`` - so with the citation
      reduced to a filename, every chunk of the file would otherwise look identical in origin.
    """
    rebound: list[Section] = []
    for index, section in enumerate(sections):
        text = section.chunk.text
        if section.title and not text.startswith(f"title: {section.title}"):
            text = f"title: {section.title}{PARAGRAPH_BREAK}{text}"
        rebound.append(
            Section(
                chunk=Chunk(page_num=index, text=text),
                content=section.content,
                category=section.category,
                id=section.id,
                sourcepage=sourcefile,
                sourcefile=sourcefile,
                title=section.title,
                url=section.url,
                tags=section.tags,
                user=section.user,
            )
        )
    return rebound


async def build_dynamic_xml_sections_if_applicable(
    *,
    file: File,
    category: Optional[str],
    check_cancel: Optional[Callable[[], Awaitable[None]]] = None,
) -> Optional[list[Section]]:
    """Parse a provisioned bot's ``.xml`` knowledge-base file, or ``None`` to fall back.

    Like the JSON counterpart this is not gated on a category: the caller opts in, and the category
    is whichever bot folder the file arrived in.
    """
    normalized_category = (category or "").strip()
    if not normalized_category or file.file_extension().lower() != ".xml":
        return None

    if check_cancel is not None:
        await check_cancel()

    try:
        root = load_xml_root(file)
    except ET.ParseError:
        logger.info("Could not read '%s' as XML; falling back to the generic parser", file.filename())
        return None

    if not is_lemon_knowledge_xml(root):
        return None

    try:
        sections = prepare_lemon_xml_sections(root, file=file, category=normalized_category)
    except ValueError:
        # lemonxml is strict by design (duplicate chunk ids, empty <content>). For a first-party
        # feed raising is right; for a provisioned bot's file it would fail the whole ingest, so
        # decline and let the generic parser take it.
        logger.warning(
            "'%s' looks like a knowledge XML export but failed validation; falling back to the generic parser",
            file.filename(),
            exc_info=True,
        )
        return None

    if not sections:
        # None, never []: `parse_file` reads an empty list as "handled", and the content2 indexer
        # deletes the file's existing documents before writing, so [] would silently drop the file.
        return None

    sections = rebind_sections_for_dynamic_bot(sections, sourcefile=os.path.basename(file.filename()))
    logger.info("Using the knowledge XML parser for '%s' (%d section(s))", file.filename(), len(sections))

    if check_cancel is not None:
        await check_cancel()

    return sections
