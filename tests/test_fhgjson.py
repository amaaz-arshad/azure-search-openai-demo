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

    prepared = prepare_fhg_dataset(payload, dataset_filename="fhg.json", category="fhg")

    assert len(prepared.documents) == 1
    search_document = prepared.documents[0]
    assert search_document.category == "fhg"
    assert search_document.sourcefile == "studium/bachelor/radiologietechnologie"
    assert search_document.sourcepage == "doc_id=page-812;parent_id=page-224"
    assert search_document.title == "Radiologietechnologie"
    assert search_document.url == "https://www.fhg-tirol.ac.at/page.cfm?vpath=studium/bachelor/radiologietechnologie"
    assert search_document.tags == ["Radiologietechnologie", "Studiengang im Überblick"]

    assert "title: Radiologietechnologie" in search_document.content
    assert "categories: Bachelor-Studiengänge, Studium" in search_document.content
    assert "tags: Radiologietechnologie, Studiengang im Überblick" in search_document.content
    assert "studium_name: Radiologietechnologie" in search_document.content
    assert "degree_type: Bachelor-Studiengänge" in search_document.content
    assert "degree_name: Radiologietechnologie (BSc)" in search_document.content
    assert "degree_abbreviation: BSc" in search_document.content
    assert "subtitle: FH-Bachelor-Studiengang" in search_document.content
    assert "content:\nErster Absatz.\n\nZweiter Absatz." in search_document.content
    assert "doc_id:" not in search_document.content
    assert "parent_id:" not in search_document.content
    assert "filename:" not in search_document.content
    assert "metadata_json:" not in search_document.content
    assert "document_json_without_content:" not in search_document.content
    assert "dataset_json:" not in search_document.content

    search_payload = search_document.to_search_document(
        storage_url="https://storage.example.net/content/fhg/fhg.json"
    )
    assert search_payload["storageUrl"] == "https://storage.example.net/content/fhg/fhg.json"
    assert search_payload["title"] == "Radiologietechnologie"
    assert search_payload["url"] == search_document.url
    assert search_payload["tags"] == search_document.tags


def test_prepare_fhg_dataset_splits_large_content_into_multiple_search_documents():
    long_paragraphs = [
        " ".join(["Dieser Studiengang vermittelt fundierte theoretische und praktische Kompetenzen."] * 14),
        " ".join(["Die Inhalte umfassen Aufnahmeverfahren, Praktika, Studienplan und Berufsperspektiven."] * 14),
        " ".join(["Zusätzlich werden Forschung, Kommunikation und interprofessionelle Zusammenarbeit behandelt."] * 14),
    ]
    payload = {"count": 1, "documents": [build_study(content="\n\n".join(long_paragraphs), doc_id="page-999")]}

    prepared = prepare_fhg_dataset(payload, dataset_filename="fhg.json", category="fhg")

    assert len(prepared.documents) > 1
    assert prepared.documents[0].id == "fhg-page-999-chunk-001"
    assert prepared.documents[-1].id.startswith("fhg-page-999-chunk-")
    assert all("title: Radiologietechnologie" in doc.content for doc in prepared.documents)
    assert all("degree_name: Radiologietechnologie (BSc)" in doc.content for doc in prepared.documents)
    assert all("chunk: " not in doc.content for doc in prepared.documents)


def test_prepare_fhg_dataset_handles_missing_parent_id():
    study = build_study(content="Kurzbeschreibung.", doc_id="page-1000")
    study.pop("parent_id")
    payload = {"count": 1, "documents": [study]}

    prepared = prepare_fhg_dataset(payload, dataset_filename="fhg.json", category="fhg")

    assert prepared.documents[0].sourcepage == "doc_id=page-1000;parent_id=none"
    assert "parent_id:" not in prepared.documents[0].content


def test_prepare_fhg_dataset_accepts_empty_content_and_keeps_metadata():
    study = build_study(content="", doc_id="page-1001", title="Empty Content Study")
    payload = {"count": 1, "documents": [study]}

    prepared = prepare_fhg_dataset(payload, dataset_filename="fhg.json", category="fhg")

    assert len(prepared.documents) == 1
    assert prepared.documents[0].id == "fhg-page-1001-chunk-001"
    assert "title: Empty Content Study" in prepared.documents[0].content
    assert "tags: Radiologietechnologie, Studiengang im Überblick" in prepared.documents[0].content
    assert "content:\n" in prepared.documents[0].content


def test_prepare_fhg_dataset_accepts_empty_filename():
    study = build_study(content="Kurzbeschreibung.", doc_id="page-1002")
    study["filename"] = ""
    payload = {"count": 1, "documents": [study]}

    prepared = prepare_fhg_dataset(payload, dataset_filename="fhg.json", category="fhg")

    assert len(prepared.documents) == 1
    assert prepared.documents[0].sourcefile == ""
    assert prepared.documents[0].sourcepage == "doc_id=page-1002;parent_id=page-224"
    assert "title: Radiologietechnologie" in prepared.documents[0].content


def test_prepare_fhg_dataset_rejects_invalid_payload():
    with pytest.raises(ValueError, match="top-level 'documents' array"):
        prepare_fhg_dataset({"count": 1}, dataset_filename="fhg.json", category="fhg")
