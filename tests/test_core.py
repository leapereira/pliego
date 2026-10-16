from __future__ import annotations

import base64
import io
from pathlib import Path

import pymupdf as fitz
import pytest
from PIL import Image
from pypdf import PdfReader

from server.core import open_pdf, parse_pages, process_core


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "ejemplo.pdf"
    with fitz.open() as doc:
        for text in ["Primera pagina: CONFIDENCIAL", "Segunda pagina", "Tercera pagina"]:
            page = doc.new_page()
            page.insert_text((72, 72), text)
        doc.save(path)
    return path


@pytest.fixture
def output(tmp_path):
    directory = tmp_path / "resultados"
    directory.mkdir()
    return directory


def page_texts(path):
    with fitz.open(path) as doc:
        return [page.get_text().strip() for page in doc]


@pytest.mark.parametrize("selection", ["0", "1,", "1,,2", "3-1", "1-4", "-1", "1.5", "2,2", "1-2,2-3", "abc", "1--2"])
def test_page_ranges_reject_malformed_or_nonexistent_pages(selection):
    with pytest.raises(ValueError):
        parse_pages(selection, 3)


def test_page_ranges_use_one_based_input_and_keep_requested_order():
    assert parse_pages("3, 1-2", 3) == [2, 0, 1]
    assert parse_pages(None, 3) == [0, 1, 2]
    assert parse_pages([2, 1], 3) == [1, 0]
    assert parse_pages("2,2", 3, allow_duplicates=True) == [1, 1]


def test_merge_preserves_all_pages_and_form_widgets(pdf, tmp_path, output):
    form = process_core("forms", [pdf], {"fields": [{"name": "nombre", "page": 2, "type": "text", "x": 72, "y": 120}], "values": {"nombre": "Ana"}}, output)[0]
    merged = process_core("merge", [pdf, form], {}, output)[0]
    with fitz.open(merged) as doc:
        assert len(doc) == 6
        assert "Primera" in doc[3].get_text()
        widgets = list(doc[4].widgets() or [])
        assert len(widgets) == 1
        assert widgets[0].field_value == "Ana"


def test_split_and_extract_use_exact_ranges(pdf, output):
    parts = process_core("split", [pdf], {"ranges": "1-2,3"}, output)
    assert len(parts) == 2
    assert len(page_texts(parts[0])) == 2
    assert page_texts(parts[1]) == ["Tercera pagina"]
    extracted = process_core("extract-pages", [pdf], {"pages": "3,1"}, output)[0]
    assert page_texts(extracted) == ["Tercera pagina", "Primera pagina: CONFIDENCIAL"]
    each = process_core("split", [pdf], {"mode": "each", "pages": "2-3"}, output)
    assert [page_texts(path)[0] for path in each] == ["Segunda pagina", "Tercera pagina"]


def test_remove_all_pages_is_rejected_and_original_is_untouched(pdf, output):
    original = pdf.read_bytes()
    with pytest.raises(ValueError, match="todas"):
        process_core("remove-pages", [pdf], {"pages": "1-3"}, output)
    assert pdf.read_bytes() == original


def test_protect_authenticate_and_unlock(pdf, output):
    protected = process_core("protect", [pdf], {"new_password": "secreto-ñ"}, output)[0]
    with fitz.open(protected) as doc:
        assert doc.needs_pass
    with pytest.raises(ValueError, match="contraseña"):
        open_pdf(protected, "incorrecta")
    with pytest.raises(ValueError, match="contraseña"):
        process_core("unlock", [protected], {}, output)
    unlocked = process_core("unlock", [protected], {"password": "secreto-ñ"}, output)[0]
    with fitz.open(unlocked) as doc:
        assert not doc.needs_pass
        assert len(doc) == 3
        assert "CONFIDENCIAL" in doc[0].get_text()


def test_redaction_removes_text_from_extraction_and_saved_streams(pdf, output):
    redacted = process_core("redact", [pdf], {"terms": "CONFIDENCIAL"}, output)[0]
    with fitz.open(redacted) as doc:
        assert "CONFIDENCIAL" not in "".join(page.get_text() for page in doc)
        assert "Primera pagina" in doc[0].get_text()
        for xref in range(1, doc.xref_length()):
            stream = doc.xref_stream(xref)
            if stream:
                assert b"CONFIDENCIAL" not in stream
    assert "CONFIDENCIAL" in page_texts(pdf)[0]


def test_redaction_does_not_claim_success_for_missing_term(pdf, output):
    with pytest.raises(ValueError, match="No se encontraron"):
        process_core("redact", [pdf], {"terms": "inexistente"}, output)


def test_form_fields_have_canonical_values_widgets_and_appearances(pdf, output):
    values = {"nombre": "Ana Pérez", "acepto": True, "pais": "Uruguay"}
    result = process_core("forms", [pdf], {"fields": [
        {"name": "nombre", "type": "text", "page": 1, "x": 72, "y": 110, "width": 220, "height": 30},
        {"name": "acepto", "type": "checkbox", "page": 2, "x": 72, "y": 110, "width": 20, "height": 20},
        {"name": "pais", "type": "choice", "page": 3, "x": 72, "y": 110, "width": 220, "height": 30, "options": ["Argentina", "Uruguay"]},
    ], "values": values}, output)[0]
    reader = PdfReader(result)
    canonical = reader.get_fields()
    assert set(canonical) == set(values)
    assert canonical["nombre"]["/V"] == "Ana Pérez"
    assert canonical["acepto"]["/V"] == "/Yes"
    assert canonical["pais"]["/V"] == "Uruguay"
    for page in reader.pages:
        for annotation in page.get("/Annots", []):
            widget = annotation.get_object()
            assert widget["/Subtype"] == "/Widget"
            assert widget["/AP"]["/N"]
            assert widget["/V"] == canonical[widget["/T"]]["/V"]
    filled = process_core("forms", [result], {"values": {"nombre": "Bruno", "acepto": False}}, output)[0]
    assert PdfReader(filled).get_fields()["nombre"]["/V"] == "Bruno"
    assert PdfReader(filled).get_fields()["acepto"]["/V"] == "/Off"


def test_form_unknown_fields_and_choice_values_are_rejected(pdf, output):
    with pytest.raises(ValueError, match="No existen"):
        process_core("forms", [pdf], {"values": {"fantasma": "x"}}, output)
    with pytest.raises(ValueError, match="opciones"):
        process_core("forms", [pdf], {"fields": [{"name": "pais", "type": "choice", "options": ["Uruguay"]}], "values": {"pais": "Brasil"}}, output)


def test_compress_preserves_searchable_text(pdf, output):
    compressed = process_core("compress", [pdf], {}, output)[0]
    assert page_texts(compressed) == page_texts(pdf)
    assert compressed.stat().st_size <= pdf.stat().st_size


@pytest.mark.parametrize("level", ["light", "balanced", "strong"])
def test_compress_accepts_frontend_levels(pdf, output, level):
    compressed = process_core("compress", [pdf], {"level": level}, output)[0]
    assert page_texts(compressed) == page_texts(pdf)


def test_rotation_crop_and_numbering_are_applied_only_to_selected_pages(pdf, output):
    rotated = process_core("rotate", [pdf], {"pages": "2", "angle": 90}, output)[0]
    with fitz.open(rotated) as doc:
        assert [page.rotation for page in doc] == [0, 90, 0]
    cropped = process_core("crop", [pdf], {"pages": "1", "margin": 20}, output)[0]
    with fitz.open(cropped) as doc:
        assert round(doc[0].rect.width) == 555
        assert round(doc[1].rect.width) == 595
    numbered = process_core("page-numbers", [pdf], {"pages": "2-3", "start": 5}, output)[0]
    assert "5 / 3" in page_texts(numbered)[1]
    assert "6 / 3" in page_texts(numbered)[2]
    assert " / " not in page_texts(numbered)[0]


def test_image_conversion_visual_signature_and_export(pdf, tmp_path, output):
    image = Image.new("RGB", (300, 120), "#34b39b")
    source = tmp_path / "foto.jpg"
    image.save(source)
    created = process_core("jpg-to-pdf", [source], {"orientation": "landscape"}, output)[0]
    with fitz.open(created) as doc:
        assert len(doc) == 1
        assert doc[0].rect.width > doc[0].rect.height
        assert len(doc[0].get_images()) == 1
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    signed = process_core("sign", [pdf], {"signature": data, "page": 3}, output)[0]
    with fitz.open(signed) as doc:
        assert len(doc[2].get_images()) == 1
        assert not list(doc[2].widgets())  # Visual signature does not invent a certificate.
    jpg = process_core("pdf-to-jpg", [signed], {"pages": "3", "dpi": 72}, output)[0]
    with Image.open(jpg) as exported:
        assert exported.format == "JPEG"
        assert exported.width == 595


def test_edit_renders_text_and_rejects_overflow(pdf, output):
    edited = process_core("edit", [pdf], {"annotations": [{"type": "text", "text": "Nota añadida", "page": 2, "x": 72, "y": 120, "width": 200, "height": 40}]}, output)[0]
    assert "Nota añadida" in page_texts(edited)[1]
    with pytest.raises(ValueError, match="no cabe"):
        process_core("edit", [pdf], {"text": "Texto demasiado largo " * 30, "width": 20, "height": 20}, output)


def test_annotations_on_rotated_pages_use_visible_preview_coordinates(pdf, output):
    rotated = process_core("rotate", [pdf], {"pages": "1", "angle": 90}, output)[0]
    edited = process_core("edit", [rotated], {"text": "NUEVO", "x": 50, "y": 40, "width": 150, "height": 50}, output)[0]
    with fitz.open(edited) as doc:
        page = doc[0]
        found = page.search_for("NUEVO")[0] * page.rotation_matrix
        assert found.x0 == pytest.approx(50, abs=1)
        assert found.y0 == pytest.approx(40, abs=3)
        assert found.width > found.height


def test_compare_escapes_untrusted_text_and_is_self_contained(pdf, tmp_path, output):
    evil = tmp_path / "<script>evil.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "<script>alert('x')</script>")
        doc.save(evil)
    report = process_core("compare", [pdf, evil], {}, output)[0].read_text()
    assert "data:image/png;base64," in report
    assert "&lt;script&gt;" in report
    assert "<script>" not in report
    assert "3 de 3" in report


def test_markdown_contains_real_text(pdf, output):
    markdown = process_core("pdf-to-markdown", [pdf], {"pages": "2"}, output)[0].read_text()
    assert "Segunda pagina" in markdown
    assert "Primera" not in markdown
