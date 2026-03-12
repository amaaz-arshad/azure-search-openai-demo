import pytest

from prepdocslib.fhgjson import prepare_fhg_dataset


def build_study(*, content: str, title: str = "Radiologietechnologie", doc_id: str = "page-812") -> dict:
    return {
        "category": ["Bachelor-Studiengänge", "Studium"],
        "content": content,
        "doc_id": doc_id,
        "filename": "studium/bachelor/radiologietechnologie",
        "metadata": {
            "degree_abbreviation": "BSc",
            "degree_name": "Radiologietechnologie (BSc)",
            "degree_type": "Bachelor-Studiengänge",
            "studium_name": "Radiologietechnologie",
            "subtitle": "FH-Bachelor-Studiengang",
        },
        "parent_id": "page-224",
        "tags": ["Radiologietechnologie", "Studiengang im Überblick"],
        "title": title,
        "url": "https://www.fhg-tirol.ac.at/page.cfm?vpath=studium/bachelor/radiologietechnologie",
    }


def test_prepare_fhg_dataset_preserves_all_non_content_fields_in_index_chunks():
    payload = {"count": 1, "documents": [build_study(content="Erster Absatz.\n\nZweiter Absatz.")]}

    prepared = prepare_fhg_dataset(payload, dataset_filename="fhg_alle_studien_20260310.json", category="fhg")

    assert len(prepared.documents) == 1
    search_document = prepared.documents[0]
    assert search_document.category == "fhg"
    assert search_document.sourcefile == "fhg_alle_studien_20260310.json"
    assert search_document.storage_url.endswith("radiologietechnologie")
    assert search_document.sourcepage == "fhg/radiologietechnologie-page-812.txt"

    assert 'categories: ["Bachelor-Studiengänge", "Studium"]' in search_document.content
    assert 'tags: ["Radiologietechnologie", "Studiengang im Überblick"]' in search_document.content
    assert 'dataset_json: {"dataset_count": 1, "dataset_filename": "fhg_alle_studien_20260310.json", "index_category": "fhg"}' in search_document.content
    assert 'metadata_json: {"degree_abbreviation": "BSc", "degree_name": "Radiologietechnologie (BSc)", "degree_type": "Bachelor-Studiengänge", "studium_name": "Radiologietechnologie", "subtitle": "FH-Bachelor-Studiengang"}' in search_document.content
    assert '"doc_id": "page-812"' in search_document.content
    assert '"parent_id": "page-224"' in search_document.content
    assert "content:\nErster Absatz.\n\nZweiter Absatz." in search_document.content

    assert len(prepared.source_blobs) == 1
    assert prepared.source_blobs[0].name == search_document.sourcepage
    assert '"content": "Erster Absatz.\\n\\nZweiter Absatz."' in prepared.source_blobs[0].text


def test_prepare_fhg_dataset_splits_large_content_into_multiple_search_documents():
    long_paragraphs = [
        " ".join(["Dieser Studiengang vermittelt fundierte theoretische und praktische Kompetenzen."] * 14),
        " ".join(["Die Inhalte umfassen Aufnahmeverfahren, Praktika, Studienplan und Berufsperspektiven."] * 14),
        " ".join(["Zusätzlich werden Forschung, Kommunikation und interprofessionelle Zusammenarbeit behandelt."] * 14),
    ]
    payload = {"count": 1, "documents": [build_study(content="\n\n".join(long_paragraphs), doc_id="page-999")]}

    prepared = prepare_fhg_dataset(payload, dataset_filename="fhg_alle_studien_20260310.json", category="fhg")

    assert len(prepared.documents) > 1
    assert prepared.documents[0].id == "fhg-page-999-chunk-001"
    assert prepared.documents[-1].id.startswith("fhg-page-999-chunk-")
    assert all('metadata_json: {"degree_abbreviation": "BSc"' in doc.content for doc in prepared.documents)
    assert all("chunk: " in doc.content for doc in prepared.documents)


def test_prepare_fhg_dataset_rejects_invalid_payload():
    with pytest.raises(ValueError, match="top-level 'documents' array"):
        prepare_fhg_dataset({"count": 1}, dataset_filename="fhg.json", category="fhg")
