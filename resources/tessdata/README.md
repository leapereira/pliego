Modelos para OCR local de Tesseract.

- `spa.traineddata`: descargado de https://github.com/tesseract-ocr/tessdata_fast el 16 de octubre de 2026. SHA256 `6f2e04d02774a18f01bed44b1111f2cd7f3ba7ac9dc4373cd3f898a40ea6b464`.
- `eng.traineddata`: modelo inglés distribuido con Homebrew Tesseract 5.5.3. SHA256 `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`.

Licencia Apache 2.0 adjunta en LICENSE. El servidor selecciona estos modelos cuando no se establece TESSDATA_PREFIX. Para otros idiomas, añade un modelo compatible a este directorio.
