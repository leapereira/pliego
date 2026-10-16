# Pliego

Un espacio local en español para trabajar con documentos, con 33 herramientas conectadas a un servidor de procesamiento Python. Los archivos se procesan en directorios temporales que se eliminan al terminar la descarga. No hay cuentas, analítica ni servicios de almacenamiento.

## Abrir en este equipo

```bash
npm start
```

Abre **http://127.0.0.1:8000**. Para instalar desde cero necesitas Python 3.12 o superior y Node.js 22 o superior:

```bash
npm run setup
npm start
```

En desarrollo, ejecuta `npm run dev` y, en otra terminal, `npm --prefix web run dev`. El servidor Vite reenvía `/api` al servidor Python. La compilación de producción se sirve desde el mismo puerto 8000. La documentación interactiva de la API está en `/api/docs`.

## Motores

El panel Ajustes muestra disponibilidad real. Las operaciones PDF habituales usan PyMuPDF. Office a PDF necesita LibreOffice; OCR necesita Tesseract e idiomas; PDF/A necesita Ghostscript. En macOS:

```bash
brew install --cask libreoffice
brew install tesseract ghostscript
```

Este proyecto incluye los modelos `eng` y `spa` de Tesseract en `resources/tessdata`. Para otros idiomas, agrega los modelos oficiales o configura `TESSDATA_PREFIX`. Se admiten las rutas `PLIEGO_LIBREOFFICE`, `PLIEGO_TESSERACT` y `PLIEGO_GHOSTSCRIPT` si los ejecutables no están en PATH.

Puedes ejecutar todos los motores en un contenedor:

```bash
docker compose up --build
```

El puerto se publica solo en `127.0.0.1`. El contenedor usa un usuario sin privilegios y no monta tus archivos locales.

## Herramientas

| Grupo | Operaciones |
| --- | --- |
| Organizar | Unir, dividir, eliminar, extraer, reordenar y escanear a PDF |
| Optimizar | Compresión, reparación estructural y OCR |
| Convertir a PDF | Imágenes, Word, PowerPoint, Excel y HTML estático |
| Convertir desde PDF | JPG, Word, PowerPoint, Excel, PDF/A y Markdown |
| Editar | Texto y figuras, rotación, numeración, marcas de agua, recorte y formularios |
| Seguridad | Contraseña, desbloqueo con contraseña, firma visual, censura permanente y comparación |
| Inteligencia | Resumen y traducción mediante una conexión configurable |

Las opciones de página empiezan en 1. Por ejemplo, `1,3-5` selecciona cuatro páginas y `3,1,2` establece un orden. Varias salidas se entregan en ZIP. La aplicación comprueba límites, formatos y contraseñas y devuelve errores; una herramienta sin motor no simula una conversión.

Los flujos de trabajo permiten encadenar hasta 10 operaciones sobre un PDF y guardar la plantilla en este navegador. Las contraseñas se excluyen de las plantillas guardadas. También puedes continuar un resultado con otra herramienta sin volver a cargarlo.

## Conectar IA

En Ajustes indica una URL de API compatible con Chat Completions, un modelo y, cuando corresponda, una clave. Para Ollama local, por ejemplo: URL `http://localhost:11434/v1` y el nombre de un modelo ya instalado. El proveedor debe estar ejecutándose. Dentro de Docker usa `http://host.docker.internal:11434/v1` y configura la clave si el proveedor la exige.

La clave introducida en la interfaz se mantiene únicamente en la memoria del servidor; no se devuelve al navegador ni se escribe en disco. Los ajustes se reinician al detener el servidor. También se pueden pasar `PLIEGO_AI_BASE_URL`, `PLIEGO_AI_MODEL` y `PLIEGO_AI_API_KEY` como variables de entorno. `.env.example` documenta los nombres; el arranque directo no carga `.env` automáticamente. El resumen y la traducción envían texto al proveedor elegido por el usuario; las demás operaciones no lo necesitan.

## Alcance y fidelidad

- La firma inserta una representación visual. No solicita firmas a terceros ni emite certificados o sellos de tiempo.
- La conversión a Office reconstruye contenido; el resultado depende de cómo esté compuesto el PDF. No garantiza equivalencia tipográfica. El OCR debe aplicarse antes de extraer texto de páginas escaneadas.
- La traducción genera un nuevo PDF con texto redistribuido. No conserva la disposición exacta del original.
- HTML a PDF trabaja con contenido estático saneado, sin ejecutar JavaScript ni cargar recursos externos. No reproduce aplicaciones web completas.
- Reparar recupera estructuras legibles; no puede reconstruir datos que faltan en el archivo de origen.
- PDF/A se genera con Ghostscript. Para un archivo sujeto a requisitos normativos, valida el resultado con veraPDF.
- El escaneo acepta capturas de cámara o imágenes desde el dispositivo que abre la aplicación. No incluye transferencia remota mediante QR.
- La comparación genera un informe local. No ofrece un servicio de revisión colaborativa.

## Verificación

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
npm test
npm run build
```

Las pruebas comprueban resultados PDF, selección de páginas, contraseñas, eliminación real de texto, formularios, conversiones y el contrato HTTP. Los motores externos se verifican cuando están instalados.

## Dependencias y distribución

Las bibliotecas y motores mantienen sus licencias respectivas. PyMuPDF y Ghostscript tienen condiciones AGPL/comerciales; revisa esas condiciones antes de distribuir una versión derivada. Los modelos OCR provienen de Tesseract (`tessdata_fast`, Apache 2.0). El código de esta aplicación se entrega en este directorio sin una licencia de redistribución añadida.
