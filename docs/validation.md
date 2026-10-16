# Verificación del proyecto

Instala las dependencias de desarrollo y ejecuta las comprobaciones:

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
npm test
npm run build
```

La suite cubre las operaciones PDF, las conversiones y la API HTTP. Los motores externos se prueban cuando están instalados; los casos que necesitan un motor ausente se omiten de forma explícita.

- Las operaciones PDF comprueban páginas, cifrado, eliminación real de contenido y formularios rellenables, tanto en sus valores canónicos como en sus apariencias.
- Las conversiones comprueban documentos Office, OCR en inglés y español, estructura PDF/A, extracción de contenido y HTML estático.
- Las pruebas HTTP comprueban cargas, límites, miniaturas, descargas, contraseñas y el tratamiento de credenciales.
- Las pruebas de IA usan respuestas controladas y no requieren una clave ni envían documentos a servicios externos.

Para revisar la interfaz, abre la aplicación y prueba el catálogo, las cargas, las descargas, los formularios y los flujos con documentos de prueba. Comprueba el diseño en escritorio y móvil, incluyendo pantallas con poco contenido y documentos de varias páginas.

La comprobación estructural de PDF/A no sustituye a un validador de conformidad como veraPDF. La construcción de Docker puede verificarse por separado con `docker compose build`.
