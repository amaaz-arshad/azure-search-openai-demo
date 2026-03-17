import io

import pytest

from prepdocslib.xmlparser import XmlParser


@pytest.mark.asyncio
async def test_xmlparser_keeps_hierarchy_for_single_document():
    file = io.StringIO(
        """
        <guide id="alpha">
            <title>Install</title>
            <step priority="high">Do it carefully</step>
        </guide>
        """
    )
    file.name = "guide.xml"
    parser = XmlParser()

    pages = [page async for page in parser.parse(file)]

    assert len(pages) == 1
    assert pages[0].page_num == 0
    assert "XML path: guide" in pages[0].text
    assert "Element: guide" in pages[0].text
    assert "@id: alpha" in pages[0].text
    assert "title: Install" in pages[0].text
    assert "step @priority: high" in pages[0].text
    assert "step text: Do it carefully" in pages[0].text


@pytest.mark.asyncio
async def test_xmlparser_splits_repeated_record_elements_into_multiple_pages():
    file = io.StringIO(
        """
        <catalog source="erp">
            <updated>2026-03-17</updated>
            <product sku="A1">
                <name>Widget</name>
                <description>Fast and durable</description>
            </product>
            <product sku="B2">
                <name>Gadget</name>
                <description>Precise and compact</description>
            </product>
        </catalog>
        """
    )
    file.name = "catalog.xml"
    parser = XmlParser()

    pages = [page async for page in parser.parse(file)]

    assert len(pages) == 2
    assert "context catalog @source: erp" in pages[0].text
    assert "context updated: 2026-03-17" in pages[0].text
    assert "XML path: catalog > product" in pages[0].text
    assert "@sku: A1" in pages[0].text
    assert "product.name: Widget" in pages[0].text
    assert "@sku: B2" in pages[1].text
    assert "product.name: Gadget" in pages[1].text
