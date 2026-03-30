import io

import pytest

from prepdocslib.csvparser import CsvParser


@pytest.mark.asyncio
async def test_csvparser_single_row_renders_labeled_record():
    file = io.BytesIO(b"col1,col2,col3\nvalue1,value2,value3")
    file.name = "test.csv"
    csvparser = CsvParser()

    pages = [page async for page in csvparser.parse(file)]

    assert len(pages) == 1
    assert pages[0].page_num == 0
    assert pages[0].offset == 0
    assert pages[0].sourcepage == "test.csv#row=2"
    assert pages[0].text == "Col1: value1\nCol2: value2\nCol3: value3"


@pytest.mark.asyncio
async def test_csvparser_multiple_rows_keep_row_boundaries_and_offsets():
    file = io.BytesIO(b"col1,col2\nvalue1,value2\nvalue3,value4")
    file.name = "test.csv"
    csvparser = CsvParser()

    pages = [page async for page in csvparser.parse(file)]

    assert len(pages) == 2
    assert pages[0].page_num == 0
    assert pages[0].sourcepage == "test.csv#row=2"
    assert pages[0].text == "Col1: value1\nCol2: value2"

    assert pages[1].page_num == 1
    assert pages[1].sourcepage == "test.csv#row=3"
    assert pages[1].offset == len(pages[0].text) + 1
    assert pages[1].text == "Col1: value3\nCol2: value4"


@pytest.mark.asyncio
async def test_csvparser_handles_semicolon_and_multiline_fields_with_metadata():
    file = io.BytesIO(
        (
            "userid;title;organizer;url;description;details;category;online\n"
            '12345;Einführung in das Insolvenzrecht;AWAK;https://awak.example;Grundlagen;'
            '"Line one\nLine two with € 150,00";Wirtschaftsrecht;X\n'
        ).encode("utf-8")
    )
    file.name = "seminars.csv"
    csvparser = CsvParser()

    pages = [page async for page in csvparser.parse(file)]

    assert len(pages) == 1
    page = pages[0]
    assert page.sourcepage == "seminars.csv#row=2"
    assert page.title == "Einführung in das Insolvenzrecht"
    assert page.url == "https://awak.example"
    assert page.user == "12345"
    assert page.tags == ["User ID: 12345", "Organizer: AWAK", "Category: Wirtschaftsrecht"]
    assert page.text == (
        "Title: Einführung in das Insolvenzrecht\n"
        "User ID: 12345\n"
        "Organizer: AWAK\n"
        "URL: https://awak.example\n"
        "Category: Wirtschaftsrecht\n"
        "Online: Yes\n\n"
        "Description:\n"
        "Grundlagen\n\n"
        "Details:\n"
        "Line one\nLine two with € 150,00"
    )


@pytest.mark.asyncio
async def test_csvparser_empty_file():
    file = io.BytesIO(b"")
    file.name = "test.csv"
    csvparser = CsvParser()

    pages = [page async for page in csvparser.parse(file)]

    assert len(pages) == 0
