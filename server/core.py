"""Local PDF processing. Coordinates are PDF points, starting at the upper left."""

from __future__ import annotations

import base64
import difflib
import html
import io
import math
import re
import shutil
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageChops, ImageOps


CORE_TOOLS = {
    "merge", "split", "remove-pages", "extract-pages", "organize", "compress",
    "repair", "rotate", "page-numbers", "watermark", "crop", "protect", "unlock",
    "edit", "sign", "redact", "forms", "jpg-to-pdf", "scan-to-pdf", "pdf-to-jpg",
    "compare", "pdf-to-markdown",
}


def parse_pages(selection, total: int, allow_duplicates: bool = False) -> list[int]:
    """Parse 1-based page ranges; never silently discard malformed pages."""
    if total < 1:
        raise ValueError("El documento no contiene páginas.")
    if selection is None or selection == "" or str(selection).strip().lower() in {"all", "todas"}:
        return list(range(total))
    if isinstance(selection, (list, tuple)):
        selection = ",".join(str(value) for value in selection)
    if not isinstance(selection, str):
        raise ValueError("Indica páginas como 1,3-5.")
    result = []
    for part in selection.split(","):
        match = re.fullmatch(r"\s*([1-9]\d*)\s*(?:-\s*([1-9]\d*)\s*)?", part)
        if not match:
            raise ValueError(f"Selección de páginas inválida: {part.strip() or '(vacía)'}. Usa 1,3-5.")
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if first > last:
            raise ValueError(f"El rango {first}-{last} está invertido.")
        if last > total:
            raise ValueError(f"La página {last} no existe. El documento tiene {total} páginas.")
        for page in range(first - 1, last):
            if not allow_duplicates and page in result:
                raise ValueError(f"La página {page + 1} está repetida.")
            result.append(page)
    return result


def open_pdf(path: Path, password: str = "") -> fitz.Document:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise ValueError(f"No se pudo abrir {path.name} como PDF. Puede estar dañado.") from exc
    if not doc.is_pdf:
        doc.close()
        raise ValueError(f"{path.name} no es un archivo PDF.")
    if doc.needs_pass and not doc.authenticate(str(password or "")):
        doc.close()
        raise ValueError(f"{path.name} necesita una contraseña correcta para abrirse.")
    if doc.page_count < 1:
        doc.close()
        raise ValueError(f"{path.name} no contiene páginas.")
    return doc


def _number(value, name: str, minimum=None, maximum=None, integer=False):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} debe ser un número válido.") from exc
    if not math.isfinite(number) or (integer and not number.is_integer()):
        raise ValueError(f"{name} debe ser un número {'entero' if integer else 'válido'}.")
    if minimum is not None and number < minimum or maximum is not None and number > maximum:
        raise ValueError(f"{name} debe estar entre {minimum if minimum is not None else '-∞'} y {maximum if maximum is not None else '∞'}.")
    return int(number) if integer else number


def _color(value="#263852") -> tuple[float, float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(_number(v, "Color", 0, 1) for v in value)
    if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
    raise ValueError("El color debe tener formato hexadecimal, por ejemplo #263852.")


def _output(outdir: Path, stem: str, label: str, extension="pdf") -> Path:
    safe = re.sub(r"[^\w. -]", "_", Path(stem).stem, flags=re.UNICODE).strip(". ")[:100] or "documento"
    path = outdir / f"{safe}-{label}.{extension}"
    number = 2
    while path.exists():
        path = outdir / f"{safe}-{label}-{number}.{extension}"
        number += 1
    return path


def _save(doc: fitz.Document, path: Path, **kwargs) -> Path:
    # Garbage collection is essential after redaction: no previous objects survive.
    options = dict(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True)
    options.update(kwargs)
    try:
        doc.save(path, **options)
        with fitz.open(path) as check:
            if check.page_count != doc.page_count:
                raise ValueError("El resultado no conserva el número de páginas esperado.")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _page(doc: fitz.Document, options: dict):
    number = _number(options.get("page", 1), "Página", 1, doc.page_count, integer=True)
    return doc[number - 1]


def _rect(page, options: dict, *, width=180, height=60):
    x = _number(options.get("x", 72), "Posición X", 0)
    y = _number(options.get("y", 72), "Posición Y", 0)
    w = _number(options.get("width", width), "Ancho", .1)
    h = _number(options.get("height", height), "Alto", .1)
    rect = fitz.Rect(x, y, x + w, y + h)
    if not page.rect.contains(rect):
        raise ValueError(f"El área indicada queda fuera de la página {page.number + 1} ({page.rect.width:.0f} × {page.rect.height:.0f} puntos).")
    # Browser previews reflect /Rotate; PyMuPDF drawing coordinates do not.
    return rect * page.derotation_matrix


def _image_data(value: str) -> bytes:
    if not isinstance(value, str) or not re.match(r"^data:image/(png|jpeg|jpg|webp);base64,", value, re.I):
        raise ValueError("La imagen debe ser una imagen PNG, JPEG o WebP en base64.")
    try:
        data = base64.b64decode(value.split(",", 1)[1], validate=True)
        if len(data) > 30 * 1024 * 1024:
            raise ValueError("La imagen supera el límite de 30 MB.")
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError("La imagen recibida no es válida.") from exc
    return data


def _text(page, text: str, rect, font_size=16, color="#263852", opacity=1):
    if not str(text).strip():
        raise ValueError("Escribe el texto que deseas añadir.")
    font_size = _number(font_size, "Tamaño de letra", 3, 300)
    shape = page.new_shape()
    space = shape.insert_textbox(rect, str(text), fontsize=font_size, fontname="helv", color=_color(color), fill_opacity=opacity, rotate=page.rotation)
    if space < 0:
        raise ValueError("El texto no cabe en el área indicada. Amplía el área o reduce el tamaño de letra.")
    shape.commit()


def _edit(doc, options):
    annotations = options.get("annotations", [])
    if not isinstance(annotations, list):
        raise ValueError("Las anotaciones deben ser una lista.")
    if options.get("text"):
        annotations = [{**options, "type": "text"}, *annotations]
    if not annotations:
        raise ValueError("Añade al menos un texto, dibujo, rectángulo o imagen.")
    for item in annotations:
        if not isinstance(item, dict):
            raise ValueError("La anotación no es válida.")
        page = _page(doc, item)
        kind = item.get("type", "text")
        if kind == "text":
            size = _number(item.get("font_size", 16), "Tamaño de letra", 3, 300)
            rect = _rect(page, item, width=max(10, page.rect.width - float(item.get("x", 72)) - 24), height=max(40, size * 3))
            _text(page, item.get("text", ""), rect, size, item.get("color", "#263852"))
        elif kind == "rect":
            rect = _rect(page, item)
            fill = _color(item["fill"]) if item.get("fill") else None
            page.draw_rect(rect, color=_color(item.get("color", "#263852")), fill=fill, width=_number(item.get("stroke_width", 2), "Grosor", .1, 50))
        elif kind == "draw":
            points = item.get("points", [])
            if not isinstance(points, list) or len(points) < 2:
                raise ValueError("Un dibujo necesita al menos dos puntos.")
            vertices = []
            for point in points:
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise ValueError("Los puntos del dibujo deben tener coordenadas X e Y.")
                p = fitz.Point(_number(point[0], "Posición X", 0, page.rect.width), _number(point[1], "Posición Y", 0, page.rect.height))
                vertices.append(p * page.derotation_matrix)
            page.draw_polyline(vertices, color=_color(item.get("color", "#263852")), width=_number(item.get("stroke_width", 2), "Grosor", .1, 50))
        elif kind == "image":
            page.insert_image(_rect(page, item), stream=_image_data(item.get("data_url", "")), rotate=page.rotation)
        else:
            raise ValueError(f"Tipo de anotación desconocido: {kind}.")


def _forms(doc, options):
    fields, values = options.get("fields", []), options.get("values", {})
    if not isinstance(fields, list) or not isinstance(values, dict):
        raise ValueError("Los campos deben ser una lista y los valores un objeto con nombre y valor.")
    if not fields and not values:
        raise ValueError("Añade campos o indica valores para rellenar el formulario.")
    names = {widget.field_name for page in doc for widget in (page.widgets() or [])}
    for field in fields:
        if not isinstance(field, dict):
            raise ValueError("El campo de formulario no es válido.")
        name = str(field.get("name", "")).strip()
        if not name or name in names:
            raise ValueError(f"Cada campo necesita un nombre único: {name or '(vacío)'}.")
        page = _page(doc, field)
        widget = fitz.Widget()
        widget.field_name = name
        widget.field_label = str(field.get("label", name))
        widget.rect = _rect(page, field, width=200, height=28)
        widget.text_fontsize = 12
        widget.text_color = (0.12, 0.16, 0.22)
        widget.border_color = (0.55, 0.61, 0.68)
        widget.border_width = 1
        widget.fill_color = (1, 1, 1)
        kind = field.get("type", "text")
        if kind == "checkbox":
            widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
            widget.field_value = False
        elif kind == "choice":
            choices = field.get("options", [])
            if not isinstance(choices, list) or not choices or not all(isinstance(v, str) for v in choices):
                raise ValueError(f"Indica las opciones del campo {name}.")
            widget.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
            widget.choice_values = choices
            widget.field_value = choices[0]
        elif kind == "text":
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.field_value = ""
            if field.get("multiline"):
                widget.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
        else:
            raise ValueError("Los campos admitidos son text, checkbox y choice.")
        page.add_widget(widget)
        names.add(name)
    missing = set(values) - names
    if missing:
        raise ValueError("No existen estos campos: " + ", ".join(sorted(missing)) + ".")
    for page in doc:
        for widget in page.widgets() or []:
            if widget.field_name not in values:
                continue
            value = values[widget.field_name]
            if widget.field_type in {fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON}:
                on = widget.on_state()
                selected = value is True or str(value).strip().lower() in {"1", "true", "yes", "sí", "si", "on", str(on).lower()}
                widget.field_value = on if selected else False
            else:
                if widget.field_type in {fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX}:
                    choices = [v[0] if isinstance(v, (list, tuple)) else v for v in widget.choice_values or []]
                    if str(value) not in choices:
                        raise ValueError(f"El valor de {widget.field_name} debe ser una de sus opciones.")
                widget.field_value = str(value)
            widget.update()


def _verify_forms(path: Path, values: dict):
    if not values:
        return
    with fitz.open(path) as doc:
        seen = {}
        for page in doc:
            for widget in page.widgets() or []:
                seen.setdefault(widget.field_name, []).append(widget.field_value)
        if set(values) - set(seen):
            raise ValueError("No se han podido conservar todos los campos del formulario.")
        for name, expected in values.items():
            for actual in seen[name]:
                if isinstance(expected, bool):
                    if (str(actual).lower() not in {"off", "false", "0", ""}) != expected:
                        raise ValueError(f"No se pudo verificar el campo {name}.")
                elif str(actual) != str(expected):
                    raise ValueError(f"No se pudo verificar el valor del campo {name}.")


def _compress(doc, options):
    level = options.get("level", "recommended")
    level = {"light": "low", "balanced": "recommended", "strong": "high"}.get(level, level)
    levels = {"low": (180, 90), "recommended": (144, 78), "high": (96, 58), "extreme": (72, 45)}
    if level not in levels:
        raise ValueError("Nivel de compresión inválido.")
    dpi, quality = levels[level]
    dpi = _number(options.get("dpi", dpi), "Resolución", 36, 600, integer=True)
    quality = _number(options.get("quality", quality), "Calidad", 10, 100, integer=True)
    placements_by_xref = {}
    for page in doc:
        for info in page.get_images(full=True):
            xref, mask = info[0], info[1]
            if mask:
                continue  # Transparency and image masks must not be flattened.
            entry = placements_by_xref.setdefault(xref, {"page": page.number, "rects": []})
            entry["rects"].extend(page.get_image_rects(xref))
    for xref, entry in placements_by_xref.items():
        try:
            placements = entry["rects"]
            if not placements:
                continue
            image = doc.extract_image(xref)
            if not image:
                continue
            with Image.open(io.BytesIO(image["image"])) as source:
                if source.mode not in {"RGB", "L"}:
                    continue
                target = (max(1, math.ceil(max(r.width for r in placements) * dpi / 72)), max(1, math.ceil(max(r.height for r in placements) * dpi / 72)))
                if source.width <= target[0] and source.height <= target[1]:
                    continue
                source.thumbnail(target, Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                source.save(buffer, format="JPEG", quality=quality, optimize=True)
                if len(buffer.getvalue()) < len(image["image"]):
                    doc[entry["page"]].replace_image(xref, stream=buffer.getvalue())
        except (OSError, RuntimeError, ValueError):
            # An unsupported image can remain unchanged; PDF streams still compress.
            continue


def _images_to_pdf(inputs, options, outdir):
    margin = _number(options.get("margin", 20), "Margen", 0, 200)
    orientation, size = options.get("orientation", "portrait"), options.get("size", "A4")
    if orientation not in {"portrait", "landscape"} or size not in {"A4", "a4", "original"}:
        raise ValueError("Elige orientación vertical u horizontal y tamaño A4 u original.")
    with fitz.open() as doc:
        for path in inputs:
            try:
                with Image.open(path) as source:
                    for frame in range(getattr(source, "n_frames", 1)):
                        source.seek(frame)
                        image = ImageOps.exif_transpose(source).convert("RGB")
                        if size == "original":
                            source_dpi = source.info.get("dpi", (96, 96))
                            if not isinstance(source_dpi, (tuple, list)) or len(source_dpi) != 2:
                                source_dpi = (96, 96)
                            width = image.width * 72 / max(1, float(source_dpi[0])) + 2 * margin
                            height = image.height * 72 / max(1, float(source_dpi[1])) + 2 * margin
                        else:
                            width, height = fitz.paper_size("a4")
                            if orientation == "landscape":
                                width, height = height, width
                        if width <= 2 * margin or height <= 2 * margin or width > 14400 or height > 14400:
                            raise ValueError("Las dimensiones de imagen o márgenes no son válidos.")
                        page = doc.new_page(width=width, height=height)
                        buffer = io.BytesIO()
                        image.save(buffer, format="JPEG", quality=95)
                        page.insert_image(fitz.Rect(margin, margin, width - margin, height - margin), stream=buffer.getvalue())
            except (OSError, Image.DecompressionBombError) as exc:
                raise ValueError(f"No se puede leer {path.name} como imagen.") from exc
        return [_save(doc, _output(outdir, "imagenes", "convertidas"))]


def _compare(inputs, options, outdir):
    if len(inputs) != 2:
        raise ValueError("Selecciona exactamente dos PDF para compararlos.")
    with open_pdf(inputs[0], options.get("password", "")) as left, open_pdf(inputs[1], options.get("password", "")) as right:
        sections = []
        changed = 0
        for index in range(max(len(left), len(right))):
            a = left[index].get_text(sort=True) if index < len(left) else ""
            b = right[index].get_text(sort=True) if index < len(right) else ""
            # Raster hashes also identify visual-only changes (images, typography, forms).
            pa = left[index].get_pixmap(dpi=60, alpha=False) if index < len(left) else None
            pb = right[index].get_pixmap(dpi=60, alpha=False) if index < len(right) else None
            visual_change = pa is None or pb is None or pa.digest != pb.digest
            different = a != b or visual_change
            changed += bool(different)
            table = difflib.HtmlDiff(wrapcolumn=70).make_table(a.splitlines(), b.splitlines(), fromdesc="Documento A", todesc="Documento B", context=True, numlines=3)
            previews = "".join(f'<figure><img alt="Página {index + 1}, documento {label}" src="data:image/png;base64,{base64.b64encode(pix.tobytes("png")).decode()}"><figcaption>Documento {label}</figcaption></figure>' if pix else f'<figure><p>Página ausente en {label}</p></figure>' for label, pix in [("A", pa), ("B", pb)])
            overlay = ""
            if visual_change and pa is not None and pb is not None:
                width, height = max(pa.width, pb.width), max(pa.height, pb.height)
                images = []
                for pix in (pa, pb):
                    image = Image.new("RGB", (width, height), "white")
                    image.paste(Image.frombytes("RGB", (pix.width, pix.height), pix.samples), (0, 0))
                    images.append(image)
                mask = ImageChops.difference(*images).convert("L").point(lambda value: min(value * 6, 255))
                highlight = Image.composite(Image.new("RGB", (width, height), "#e52f58"), Image.blend(*images, .5), mask)
                buffer = io.BytesIO()
                highlight.save(buffer, format="PNG")
                encoded = base64.b64encode(buffer.getvalue()).decode()
                overlay = f'<details><summary>Ver superposición de diferencias visuales</summary><figure><img style="max-width:100%" alt="Diferencias resaltadas en rosa" src="data:image/png;base64,{encoded}"><figcaption>El color rosa identifica diferencias de píxeles entre ambas páginas alineadas por la esquina superior izquierda.</figcaption></figure></details>'
            sections.append(f'<section><h2>Página {index + 1} · {"Con cambios" if different else "Sin cambios"}</h2><div class="previews">{previews}</div>{overlay}<div class="table-wrap">{table}</div></section>')
        document = f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Comparación de PDF</title><style>body{{font:15px system-ui;color:#213047;background:#f2f4f7;margin:0;padding:36px}}main{{max-width:1280px;margin:auto}}section{{padding:24px;background:white;border:1px solid #dce2e9;border-radius:16px;margin:24px 0}}h1{{font-size:32px}}h2{{font-size:20px}}.previews{{display:flex;gap:20px}}figure{{flex:1;min-width:0;margin:12px 0}}figure img{{max-width:100%;border:1px solid #ddd}}figcaption{{padding:8px}}.table-wrap{{overflow:auto}}table.diff{{font:12px monospace;border-spacing:4px;width:100%}}.diff_header{{background:#edf0f4}}.diff_add{{background:#d3f4df}}.diff_sub{{background:#ffe0e0}}.diff_chg{{background:#fff2bd}}td{{vertical-align:top}}@media(max-width:600px){{body{{padding:12px}}.previews{{display:block}}}}</style><main><h1>Comparación de documentos</h1><p>{html.escape(inputs[0].name)} y {html.escape(inputs[1].name)}</p><p>{changed} de {max(len(left), len(right))} páginas presentan cambios en texto o aspecto visual. Esta comparación no comprueba certificados ni equivalencia semántica.</p>{''.join(sections)}</main></html>'''
        path = _output(outdir, "comparacion", "informe", "html")
        path.write_text(document, encoding="utf-8")
        return [path]


def _markdown(doc, pages):
    lines = []
    for number in pages:
        page = doc[number]
        blocks = page.get_text("dict", sort=True)["blocks"]
        sizes = Counter(round(span["size"], 1) for block in blocks if "lines" in block for line in block["lines"] for span in line["spans"] for _ in span["text"] if not _.isspace())
        body_size = sizes.most_common(1)[0][0] if sizes else 12
        lines.append(f"<!-- Página {number + 1} -->\n")
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                text = "".join(span["text"] for span in line["spans"]).strip()
                if not text:
                    continue
                largest = max(span["size"] for span in line["spans"])
                text = re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", text)
                prefix = "# " if largest >= body_size * 1.65 else "## " if largest >= body_size * 1.3 else ""
                if text.startswith(("• ", "· ")):
                    text = "- " + text[2:]
                lines.append(prefix + text + ("\n" if prefix else ""))
            lines.append("")
        lines.append("\n---\n")
    return "\n".join(lines).rstrip("\n- ") + "\n"


def process_core(tool: str, inputs: list[Path], options: dict, outdir: Path) -> list[Path]:
    """Process a local job and return actual output paths, or a Spanish ValueError."""
    if tool not in CORE_TOOLS:
        raise ValueError(f"Herramienta desconocida: {tool}.")
    if not inputs:
        raise ValueError("Selecciona al menos un archivo.")
    if not isinstance(options, dict):
        raise ValueError("Las opciones no son válidas.")
    inputs = [Path(path) for path in inputs]
    for path in inputs:
        if not path.is_file():
            raise ValueError(f"No se encuentra el archivo {path.name}.")
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        if tool in {"jpg-to-pdf", "scan-to-pdf"}:
            return _images_to_pdf(inputs, options, outdir)
        if tool == "compare":
            return _compare(inputs, options, outdir)
        if tool == "merge":
            with ExitStack() as stack:
                docs = [stack.enter_context(open_pdf(path, options.get("password", ""))) for path in inputs]
                result = stack.enter_context(fitz.open())
                for doc in docs:
                    for number in parse_pages(options.get("pages"), len(doc)):
                        result.insert_pdf(doc, from_page=number, to_page=number, widgets=True)
                return [_save(result, _output(outdir, "documentos", "unidos"))]
        outputs = []
        for source in inputs:
            with open_pdf(source, options.get("password", "")) as doc:
                pages = parse_pages(options.get("pages"), len(doc))
                if tool == "split":
                    mode = options.get("mode", "ranges")
                    if mode == "each":
                        groups = [[page] for page in pages]
                    elif mode == "ranges":
                        ranges = options.get("ranges", options.get("pages", ""))
                        if not isinstance(ranges, str) or not ranges.strip():
                            raise ValueError("Indica los rangos para dividir, por ejemplo 1-3,4-6.")
                        groups = [parse_pages(part, len(doc)) for part in ranges.split(",")]
                    else:
                        raise ValueError("Elige división por rangos o por cada página.")
                    for index, group in enumerate(groups, 1):
                        with fitz.open() as part:
                            for number in group:
                                part.insert_pdf(doc, from_page=number, to_page=number, widgets=True)
                            outputs.append(_save(part, _output(outdir, source.stem, f"parte-{index}")))
                    continue
                if tool in {"remove-pages", "extract-pages", "organize"}:
                    if tool == "remove-pages":
                        if not options.get("pages"):
                            raise ValueError("Indica las páginas que deseas eliminar.")
                        keep = [number for number in range(len(doc)) if number not in set(pages)]
                        if not keep:
                            raise ValueError("No se pueden eliminar todas las páginas del documento.")
                    elif tool == "organize":
                        keep = parse_pages(options.get("order") or options.get("pages"), len(doc), allow_duplicates=True)
                    else:
                        keep = pages
                    # Document.select retains document-level structures and form fields.
                    doc.select(keep)
                elif tool == "rotate":
                    angle = _number(options.get("angle", 90), "Ángulo", -360, 360, integer=True)
                    if angle % 90:
                        raise ValueError("La rotación debe ser un múltiplo de 90 grados.")
                    for number in pages:
                        doc[number].set_rotation((doc[number].rotation + angle) % 360)
                elif tool == "page-numbers":
                    start = _number(options.get("start", 1), "Número inicial", 0, 999999, integer=True)
                    position = options.get("position", "bottom-center")
                    if position not in {"bottom-left", "bottom-center", "bottom-right", "top-left", "top-center", "top-right"}:
                        raise ValueError("La posición del número de página no es válida.")
                    font_size = _number(options.get("font_size", 11), "Tamaño de letra", 5, 60)
                    template = str(options.get("format", "{n} / {total}"))
                    if not template.strip():
                        raise ValueError("Indica el formato del número de página.")
                    for index, number in enumerate(pages):
                        page = doc[number]
                        label = template.replace("{n}", str(start + index)).replace("{total}", str(len(doc))).replace("{page}", str(number + 1))
                        length = fitz.get_text_length(label, fontname="helv", fontsize=font_size)
                        x = 30 if position.endswith("left") else page.rect.width - length - 30 if position.endswith("right") else (page.rect.width - length) / 2
                        if x < 0:
                            raise ValueError("El número de página no cabe. Reduce el tamaño o el texto.")
                        y = 30 + font_size if position.startswith("top") else page.rect.height - 24
                        page.insert_text(fitz.Point(x, y) * page.derotation_matrix, label, fontsize=font_size, color=_color(options.get("color", "#455168")), rotate=page.rotation)
                elif tool == "watermark":
                    text = str(options.get("text", ""))
                    if not text.strip():
                        raise ValueError("Escribe el texto de la marca de agua.")
                    opacity = _number(options.get("opacity", .2), "Opacidad", 0, 1)
                    size = _number(options.get("font_size", 40), "Tamaño de letra", 3, 300)
                    for number in pages:
                        page = doc[number]
                        rect = fitz.Rect(24, page.rect.height / 2 - size, page.rect.width - 24, page.rect.height / 2 + size * 2)
                        shape = page.new_shape()
                        if shape.insert_textbox(rect * page.derotation_matrix, text, fontname="helv", fontsize=size, color=_color(options.get("color", "#596579")), align=1, fill_opacity=opacity, rotate=page.rotation) < 0:
                            raise ValueError("La marca de agua no cabe. Reduce el tamaño de letra.")
                        shape.commit(overlay=True)
                elif tool == "crop":
                    margins = options.get("margins", {})
                    if not isinstance(margins, dict):
                        raise ValueError("Los márgenes deben indicar top, right, bottom y left.")
                    top, right, bottom, left = [_number(margins.get(key, options.get("margin", 24)), "Margen", 0) for key in ("top", "right", "bottom", "left")]
                    for number in pages:
                        page = doc[number]
                        old = page.cropbox
                        rect = fitz.Rect(old.x0 + left, old.y0 + top, old.x1 - right, old.y1 - bottom)
                        if rect.is_empty or rect.width < 1 or rect.height < 1:
                            raise ValueError("Los márgenes eliminan toda la página.")
                        page.set_cropbox(rect)
                elif tool == "compress":
                    _compress(doc, options)
                elif tool == "protect":
                    password = str(options.get("new_password", ""))
                    if not password or len(password.encode("utf-8")) > 128:
                        raise ValueError("Escribe una contraseña nueva de entre 1 y 128 bytes.")
                    outputs.append(_save(doc, _output(outdir, source.stem, "protegido"), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=password, user_pw=password))
                    continue
                elif tool == "unlock":
                    pass  # Opening has authenticated; default save removes encryption.
                elif tool == "edit":
                    _edit(doc, options)
                elif tool == "sign":
                    page = _page(doc, options)
                    rect = _rect(page, options, width=180, height=70)
                    if options.get("signature"):
                        page.insert_image(rect, stream=_image_data(options["signature"]), rotate=page.rotation)
                    else:
                        _text(page, options.get("text", ""), rect, options.get("font_size", 24), options.get("color", "#182b4d"))
                elif tool == "redact":
                    terms = options.get("terms", "")
                    if isinstance(terms, str):
                        terms = [term.strip() for term in terms.splitlines() if term.strip()]
                    if not isinstance(terms, list) or not all(isinstance(term, str) and term.strip() for term in terms):
                        raise ValueError("Indica los términos a censurar, uno por línea.")
                    rects = options.get("rects", [])
                    if not isinstance(rects, list) or not all(isinstance(rect, dict) for rect in rects):
                        raise ValueError("Las áreas de censura no son válidas.")
                    if not terms and not rects:
                        raise ValueError("Indica texto o áreas para censurar.")
                    count = 0
                    fill = _color(options.get("color", "#000000"))
                    for number in pages:
                        page = doc[number]
                        for term in terms:
                            for found in page.search_for(term):
                                page.add_redact_annot(found, fill=fill)
                                count += 1
                        for item in rects:
                            target = _number(item.get("page", 1), "Página", 1, len(doc), integer=True) - 1
                            if target == number:
                                page.add_redact_annot(_rect(page, item), fill=fill)
                                count += 1
                        if page.first_annot:
                            page.apply_redactions(images=2, graphics=2, text=0)
                    if not count:
                        raise ValueError("No se encontraron los términos en las páginas elegidas. Si es un escaneo, usa OCR primero o selecciona un área.")
                    # Strip metadata that might contain a copy of sensitive text.
                    doc.set_metadata({})
                    doc.del_xml_metadata()
                elif tool == "forms":
                    _forms(doc, options)
                elif tool == "pdf-to-jpg":
                    previous_outputs = len(outputs)
                    mode = options.get("mode", "pages")
                    quality = _number(options.get("quality", 85), "Calidad", 10, 100, integer=True)
                    if mode == "pages":
                        dpi = _number(options.get("dpi", 144), "Resolución", 36, 400, integer=True)
                        for number in pages:
                            page = doc[number]
                            if page.rect.width * page.rect.height * (dpi / 72) ** 2 > 80_000_000:
                                raise ValueError("La página es demasiado grande para esa resolución. Reduce los DPI.")
                            pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=fitz.csRGB)
                            path = _output(outdir, source.stem, f"pagina-{number + 1}", "jpg")
                            pix.save(path, jpg_quality=quality)
                            outputs.append(path)
                    elif mode == "images":
                        seen = set()
                        for number in pages:
                            for index, info in enumerate(doc[number].get_images(full=True), 1):
                                xref = info[0]
                                if xref in seen:
                                    continue
                                seen.add(xref)
                                image = doc.extract_image(xref)
                                if not image:
                                    continue
                                # Preserve transparency / source encoding when extracting embedded images.
                                path = _output(outdir, source.stem, f"imagen-p{number + 1}-{index}", image["ext"])
                                if info[1]:
                                    base = fitz.Pixmap(doc, xref)
                                    mask = fitz.Pixmap(doc, info[1])
                                    path = _output(outdir, source.stem, f"imagen-p{number + 1}-{index}", "png")
                                    fitz.Pixmap(base, mask).save(path)
                                else:
                                    path.write_bytes(image["image"])
                                outputs.append(path)
                        if len(outputs) == previous_outputs:
                            raise ValueError("No hay imágenes incrustadas en las páginas elegidas. Usa el modo de páginas completas.")
                    else:
                        raise ValueError("Elige páginas completas o extracción de imágenes.")
                    continue
                elif tool == "pdf-to-markdown":
                    path = _output(outdir, source.stem, "texto", "md")
                    text = _markdown(doc, pages)
                    if not any(doc[number].get_text().strip() for number in pages):
                        raise ValueError("No se detectó texto. Usa OCR primero si el documento es un escaneo.")
                    path.write_text(text, encoding="utf-8")
                    outputs.append(path)
                    continue
                elif tool != "repair":
                    raise ValueError(f"La herramienta {tool} no está implementada.")
                labels = {"compress": "comprimido", "repair": "reparado", "remove-pages": "paginas-eliminadas", "extract-pages": "paginas-extraidas", "organize": "organizado", "rotate": "rotado", "page-numbers": "numerado", "watermark": "marca-de-agua", "crop": "recortado", "unlock": "desbloqueado", "edit": "editado", "sign": "firma-visual", "redact": "censurado", "forms": "formulario"}
                path = _save(doc, _output(outdir, source.stem, labels[tool]), clean=tool in {"repair", "redact"})
                if tool == "compress" and path.stat().st_size >= source.stat().st_size:
                    original = _output(outdir, source.stem, "ya-optimizado")
                    shutil.copyfile(source, original)
                    path.unlink()
                    path = original
                if tool == "forms":
                    try:
                        _verify_forms(path, options.get("values", {}))
                    except ValueError:
                        path.unlink(missing_ok=True)
                        raise
                outputs.append(path)
        if not outputs:
            raise ValueError("No se generó ningún archivo.")
        return outputs
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"No se pudo completar la operación: {exc}") from exc
