import io
import zipfile

import fitz
import pytest
from fastapi.testclient import TestClient

from server.main import app


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


@pytest.fixture
def pdf_bytes():
    with fitz.open() as doc:
        for n in range(1, 4):
            doc.new_page().insert_text((72, 90), f"Documento de prueba - pagina {n}")
        return doc.tobytes()


def test_catalog_and_local_origin_boundary(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert len(response.json()["catalog"]) == 33
    assert {"merge", "redact", "forms"} <= set(response.json()["tools"])
    assert response.headers["cache-control"] == "no-store"
    response = client.put("/api/settings", json={"ai_base_url": "http://localhost:11434/v1", "ai_model": ""}, headers={"Origin": "https://example.com"})
    assert response.status_code == 403
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_inspect_preview_and_merge(client, pdf_bytes):
    response = client.post("/api/inspect", files={"file": ("prueba.pdf", pdf_bytes, "application/pdf")})
    assert response.status_code == 200
    assert response.json()["page_count"] == 3
    preview = client.post("/api/preview", files={"file": ("prueba.pdf", pdf_bytes)}, data={"page": 2})
    assert preview.status_code == 200 and preview.content.startswith(b"\x89PNG")
    response = client.post("/api/process/merge", files=[("files", ("../uno.pdf", pdf_bytes)), ("files", ("dos.pdf", pdf_bytes))])
    assert response.status_code == 200
    with fitz.open(stream=response.content, filetype="pdf") as result:
        assert len(result) == 6
        assert "pagina 1" in result[3].get_text()
    assert "attachment" in response.headers["content-disposition"]


def test_split_downloads_zip_and_strict_errors(client, pdf_bytes):
    response = client.post("/api/process/split", files={"files": ("prueba.pdf", pdf_bytes)}, data={"options": '{"mode":"each"}'})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert len(bundle.namelist()) == 3
        assert all(".." not in n for n in bundle.namelist())
    bad = client.post("/api/process/extract-pages", files={"files": ("prueba.pdf", pdf_bytes)}, data={"options": '{"pages":"99"}'})
    assert bad.status_code == 400
    invalid = client.post("/api/process/rotate", files={"files": ("prueba.pdf", pdf_bytes)}, data={"options": "[]"})
    assert invalid.status_code == 400
    unknown = client.post("/api/process/nonexistent")
    assert unknown.status_code == 404


def test_ai_credentials_never_returned(client):
    from server.main import settings
    previous = dict(settings)
    try:
        result = client.put("/api/settings", json={"ai_base_url": "http://localhost:11434/v1", "ai_model": "test-model", "ai_api_key": "test-secret-not-returned"})
        assert result.status_code == 200
        assert "test-secret" not in result.text
        assert "test-secret" not in client.get("/api/settings").text
        assert client.get("/api/health").json()["ai_configured"]
    finally:
        settings.clear()
        settings.update(previous)


def test_encrypted_inspect_and_conversion_with_password(client, pdf_bytes):
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        protected = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secreto", owner_pw="propietario")
    inspection = client.post("/api/inspect", files={"file": ("protegido.pdf", protected)}, data={"password": "secreto"})
    assert inspection.status_code == 200
    assert inspection.json()["encrypted"] is True
    converted = client.post("/api/process/pdf-to-powerpoint", files={"files": ("protegido.pdf", protected)}, data={"options": '{"password":"secreto"}'})
    assert converted.status_code == 200
    with zipfile.ZipFile(io.BytesIO(converted.content)) as bundle:
        assert "ppt/presentation.xml" in bundle.namelist()


def test_invalid_origin_and_widget_types(client):
    invalid = client.put("/api/settings", json={}, headers={"Origin": "http://localhost:invalid"})
    assert invalid.status_code == 403
    with fitz.open() as doc:
        page = doc.new_page()
        widget = fitz.Widget()
        widget.field_name = "acepto"
        widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        widget.rect = fitz.Rect(40, 40, 60, 60)
        page.add_widget(widget)
        data = doc.tobytes()
    result = client.post("/api/inspect", files={"file": ("formulario.pdf", data)})
    assert result.status_code == 200
    field = result.json()["fields"][0]
    assert field["type"] == "checkbox" and field["value"] is False
