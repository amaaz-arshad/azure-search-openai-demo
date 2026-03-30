import io

from prepdocslib.listfilestrategy import File
from prepdocslib.page import ImageOnPage, Page
from prepdocslib.textprocessor import combine_text_with_figures, process_text
from prepdocslib.textsplitter import Chunk


def test_combine_text_with_figures_no_description():
    """Test combine_text_with_figures when image has no description."""
    image = ImageOnPage(
        bytes=b"fake",
        bbox=(0, 0, 100, 100),
        filename="test.png",
        page_num=1,
        figure_id="fig_1",
        placeholder="[PLACEHOLDER_fig_1]",
        description=None,
    )

    page = Page(page_num=1, text="Some text [PLACEHOLDER_fig_1] more text", offset=0)
    page.images = [image]

    # Should keep placeholder when no description
    combine_text_with_figures(page)

    assert "[PLACEHOLDER_fig_1]" in page.text
    assert "<figure>" not in page.text


def test_combine_text_with_figures_placeholder_not_found(caplog):
    """Test combine_text_with_figures when placeholder is not in text."""
    import logging

    image = ImageOnPage(
        bytes=b"fake",
        bbox=(0, 0, 100, 100),
        filename="test.png",
        page_num=1,
        figure_id="fig_1",
        placeholder="[PLACEHOLDER_fig_1]",
        description="A test image",
    )

    page = Page(page_num=1, text="Some text without placeholder", offset=0)
    page.images = [image]

    with caplog.at_level(logging.WARNING):
        combine_text_with_figures(page)

    assert "Placeholder not found for figure fig_1" in caplog.text


def test_combine_text_with_figures_replaces_successfully():
    """Test combine_text_with_figures successfully replaces placeholder."""
    image = ImageOnPage(
        bytes=b"fake",
        bbox=(0, 0, 100, 100),
        filename="test.png",
        page_num=1,
        figure_id="fig_1",
        title="Test Figure",
        placeholder="[PLACEHOLDER_fig_1]",
        description="A test image",
    )

    page = Page(page_num=1, text="Some text [PLACEHOLDER_fig_1] more text", offset=0)
    page.images = [image]

    combine_text_with_figures(page)

    assert "[PLACEHOLDER_fig_1]" not in page.text
    assert "<figure>" in page.text
    assert "A test image" in page.text


def test_process_text_propagates_page_metadata_to_sections():
    file = File(content=io.BytesIO(b"unused"))
    file.content.name = "seminars.csv"
    page = Page(
        page_num=0,
        offset=0,
        text="Title: Einführung in das Insolvenzrecht\nCategory: Wirtschaftsrecht",
        sourcepage="seminars.csv#row=2",
        title="Einführung in das Insolvenzrecht",
        url="https://awak.example",
        tags=["Category: Wirtschaftsrecht"],
        user="12345",
    )

    class StubSplitter:
        def split_pages(self, pages):
            yield Chunk(page_num=pages[0].page_num, text=pages[0].text)

    sections = process_text([page], file, StubSplitter(), category="rak")

    assert len(sections) == 1
    assert sections[0].sourcepage == "seminars.csv#row=2"
    assert sections[0].title == "Einführung in das Insolvenzrecht"
    assert sections[0].url == "https://awak.example"
    assert sections[0].tags == ["Category: Wirtschaftsrecht"]
    assert sections[0].user == "12345"
