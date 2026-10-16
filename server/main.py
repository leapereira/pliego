"""HTTP local: cargas temporales, operaciones reales y entrega sin persistencia."""
from __future__ import annotations

import asyncio
import io
import json
import mimetypes
import os
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import pymupdf as fitz
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .core import process_core
from .conversions import detect_engines, process_conversion

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_MB = int(os.getenv("PLIEGO_MAX_FILE_MB", "100"))
MAX_FILES = 20
MAX_PAGES = 1500
CORE_TOOLS = {
    "merge", "split", "remove-pages", "extract-pages", "organize", "compress",
    "repair", "rotate", "page-numbers", "watermark", "crop", "protect", "unlock",
    "edit", "sign", "redact", "forms", "jpg-to-pdf", "scan-to-pdf", "pdf-to-jpg",
    "compare", "pdf-to-markdown",
}
CONVERSION_TOOLS = {
    "word-to-pdf", "powerpoint-to-pdf", "excel-to-pdf", "pdf-to-word",
    "pdf-to-powerpoint", "pdf-to-excel", "html-to-pdf", "pdf-to-pdfa", "ocr",
    "summarize", "translate",
}
ALL_TOOLS = CORE_TOOLS | CONVERSION_TOOLS
settings = {
    "ai_base_url": os.getenv("PLIEGO_AI_BASE_URL", "http://localhost:11434/v1"),
    "ai_model": os.getenv("PLIEGO_AI_MODEL", ""),
    "ai_api_key": os.getenv("PLIEGO_AI_API_KEY", ""),
}
processing_slots = asyncio.Semaphore(2)
app = FastAPI(title="Pliego", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])


@app.middleware("http")
async def local_boundaries(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
        try:
            parsed = urlparse(origin)
            allowed = parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"} and parsed.port in {request.url.port, 8000, 5173}
        except ValueError:
            allowed = False
        if not allowed:
            return JSONResponse({"detail": "Solo se admiten solicitudes desde la aplicación local."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def ai_ready() -> bool:
    host = urlparse(settings["ai_base_url"]).hostname
    return bool(settings["ai_model"] and (settings["ai_api_key"] or host in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}))


@app.get("/api/health")
def health():
    engines = detect_engines()
    available = set(ALL_TOOLS)
    reasons = {}
    for ids, engine, reason in [
        (["word-to-pdf", "powerpoint-to-pdf", "excel-to-pdf"], "libreoffice", "Instala LibreOffice para convertir documentos Office."),
        (["ocr"], "tesseract", "Instala Tesseract para reconocer texto en documentos escaneados."),
        (["pdf-to-pdfa"], "ghostscript", "Instala Ghostscript para crear archivos PDF/A."),
        (["pdf-to-word"], "pdf2docx", "Instala la dependencia pdf2docx."),
    ]:
        if not engines.get(engine):
            for tool in ids:
                available.discard(tool)
                reasons[tool] = reason
    if not ai_ready():
        for tool in ("summarize", "translate"):
            available.discard(tool)
            reasons[tool] = "Configura un modelo local o una conexión de IA en Ajustes."
    return {"status": "ok", "version": "1.0.0", "engines": engines,
            "ai_configured": ai_ready(), "tools": sorted(available),
            "unavailable": reasons, "catalog": sorted(ALL_TOOLS),
            "limits": {"max_file_mb": MAX_FILE_MB, "max_files": MAX_FILES, "max_pages": MAX_PAGES}}


@app.get("/api/settings")
def read_settings():
    return {"ai_base_url": settings["ai_base_url"], "ai_model": settings["ai_model"], "ai_configured": ai_ready()}


class AISettings(BaseModel):
    ai_base_url: str = Field(max_length=500)
    ai_model: str = Field(max_length=200)
    ai_api_key: str | None = Field(default=None, max_length=4096)


@app.put("/api/settings")
def update_settings(value: AISettings):
    parsed = urlparse(value.ai_base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(400, "La URL del proveedor debe ser HTTP o HTTPS y no incluir credenciales.")
    settings.update(ai_base_url=value.ai_base_url.rstrip("/"), ai_model=value.ai_model.strip())
    if value.ai_api_key is not None:
        settings["ai_api_key"] = value.ai_api_key
    return read_settings()


def safe_name(filename: str | None, index: int) -> str:
    original = Path((filename or "documento.pdf").replace("\\", "/")).name
    name = re.sub(r"[^\w. -]", "_", original, flags=re.UNICODE).strip(" .") or "documento.pdf"
    return f"{index:02d}-{name[:160]}"


async def save_upload(upload: UploadFile, directory: Path, index: int) -> Path:
    destination = directory / safe_name(upload.filename, index)
    size = 0
    try:
        with destination.open("wb") as stream:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_MB * 1024 * 1024:
                    raise HTTPException(413, f"Cada archivo puede ocupar hasta {MAX_FILE_MB} MB.")
                stream.write(chunk)
    finally:
        await upload.close()
    if not size:
        raise HTTPException(400, "El archivo está vacío.")
    return destination


def open_document(data: bytes, password: str = ""):
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("No se pudo abrir el PDF. Revisa que el archivo sea válido.") from exc
    if doc.needs_pass and not doc.authenticate(password):
        doc.close()
        raise ValueError("El PDF está protegido. Introduce su contraseña para continuar.")
    if not 0 < len(doc) <= MAX_PAGES:
        doc.close()
        raise ValueError(f"Se admiten documentos de 1 a {MAX_PAGES} páginas.")
    return doc


async def read_pdf_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_FILE_MB * 1024 * 1024 + 1)
    await file.close()
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"El límite es {MAX_FILE_MB} MB por archivo.")
    return data


@app.post("/api/inspect")
async def inspect(file: UploadFile = File(...), password: str = Form("")):
    data = await read_pdf_upload(file)
    def work():
        with open_document(data, password) as doc:
            fields, pages = [], []
            for index, page in enumerate(doc):
                pages.append({"number": index + 1, "width": page.rect.width, "height": page.rect.height})
                for widget in page.widgets() or []:
                    kind = "checkbox" if widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX else "choice" if widget.field_type in {fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX} else "text"
                    value = widget.field_value
                    if kind == "checkbox":
                        value = value not in (None, "", "Off", "0", False)
                    fields.append({"name": widget.field_name, "type": kind,
                                   "value": value, "page": index + 1,
                                   "x": widget.rect.x0, "y": widget.rect.y0,
                                   "width": widget.rect.width, "height": widget.rect.height,
                                   "options": widget.choice_values or []})
            return {"pages": pages, "page_count": len(doc), "fields": fields, "encrypted": bool(doc.needs_pass)}
    try:
        return await run_in_threadpool(work)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/preview")
async def preview(file: UploadFile = File(...), page: int = Form(1), password: str = Form("")):
    data = await read_pdf_upload(file)
    def work():
        with open_document(data, password) as doc:
            if page < 1 or page > len(doc):
                raise ValueError("La página seleccionada no existe.")
            source = doc[page - 1]
            scale = min(1.3, 1200 / max(source.rect.width, source.rect.height))
            return source.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
    try:
        return Response(await run_in_threadpool(work), media_type="image/png")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/process/{tool}")
async def process(tool: str, files: list[UploadFile] = File(default=[]), options: str = Form("{}")):
    if tool not in ALL_TOOLS:
        raise HTTPException(404, "Esta herramienta no existe.")
    if len(options) > 1_000_000:
        raise HTTPException(413, "Las opciones exceden el tamaño permitido.")
    try:
        opts = json.loads(options)
        if not isinstance(opts, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(400, "Las opciones deben ser un objeto JSON válido.")
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"Puedes procesar hasta {MAX_FILES} archivos a la vez.")
    if not files and not (tool == "html-to-pdf" and (opts.get("html") or opts.get("url"))):
        raise HTTPException(400, "Selecciona al menos un archivo.")
    if tool not in health()["tools"]:
        raise HTTPException(503, health()["unavailable"].get(tool, "El motor no está disponible."))
    temp = tempfile.TemporaryDirectory(prefix="pliego-")
    directory = Path(temp.name)
    try:
        inputs = [await save_upload(file, directory, i) for i, file in enumerate(files)]
        outdir = directory / "salida"
        outdir.mkdir()
        def work():
            # Validate page counts before expensive document operations.
            pdf_input = tool not in {"word-to-pdf", "powerpoint-to-pdf", "excel-to-pdf", "jpg-to-pdf", "scan-to-pdf", "html-to-pdf", "repair"}
            for index, path in enumerate(inputs):
                if pdf_input:
                    with open_document(path.read_bytes(), str(opts.get("password", ""))) as doc:
                        if tool in CONVERSION_TOOLS and doc.needs_pass:
                            decrypted = directory / f"{path.stem}-abierto.pdf"
                            doc.save(decrypted, encryption=fitz.PDF_ENCRYPT_NONE)
                            inputs[index] = decrypted
            if tool in CORE_TOOLS:
                outputs = process_core(tool, inputs, opts, outdir)
            else:
                outputs = process_conversion(tool, inputs, opts, outdir, dict(settings))
            if not outputs or any(not p.is_file() or not p.stat().st_size for p in outputs):
                raise ValueError("El motor no pudo generar un resultado. Revisa el archivo y las opciones.")
            if len(outputs) == 1:
                return outputs[0]
            bundle = outdir / "pliego-resultados.zip"
            used = set()
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                for index, output in enumerate(outputs):
                    name = output.name
                    if name in used:
                        name = f"{index + 1}-{name}"
                    used.add(name)
                    archive.write(output, arcname=name)
            return bundle
        async with processing_slots:
            output = await run_in_threadpool(work)
        note = {
            "sign": "Firma visual insertada. No contiene certificado digital.",
            "translate": "Traduccion en un nuevo documento con texto redistribuido.",
            "pdf-to-pdfa": "Conversion realizada. Valida conformidad con veraPDF para archivo normativo.",
            "html-to-pdf": "HTML estatico saneado; sin JavaScript ni recursos externos.",
            "repair": "Recuperacion estructural realizada. Revisa el contenido del documento.",
        }.get(tool, "")
        return FileResponse(output, filename=output.name,
                            media_type=mimetypes.guess_type(output.name)[0] or "application/octet-stream",
                            headers={"X-Pliego-Note": note}, background=BackgroundTask(temp.cleanup))
    except HTTPException:
        temp.cleanup()
        raise
    except (ValueError, RuntimeError) as exc:
        temp.cleanup()
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        temp.cleanup()
        raise HTTPException(422, "No se pudo procesar el documento. Comprueba el formato, la contraseña y las opciones.")


DIST = ROOT / "web" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
else:
    @app.get("/")
    def missing_frontend():
        return JSONResponse({"message": "Pliego está listo. Ejecuta npm --prefix web run build para abrir la interfaz.",
                             "api": "/api/docs"})
