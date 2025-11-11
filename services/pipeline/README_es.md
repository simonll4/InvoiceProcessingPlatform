# Pipeline de Extraccion de Facturas

Este documento describe en espanol el funcionamiento del pipeline, la responsabilidad de cada modulo y las rutas que sigue un documento segun sea PDF o imagen.

## Vision general

El punto de entrada es `service/pipeline.py`. La funcion `run_pipeline` recibe la ruta de un archivo, calcula su hash, reutiliza resultados almacenados cuando existen y coordina al resto de modulos para obtener un JSON normalizado del esquema `invoice_v1`.

## Etapas del flujo

1. **Deteccion de fuente (`ingest/loader.py`)**
   - `detect_source` revisa la extension y el MIME del archivo para decidir si se trata de un PDF (`"pdf"`) o de una imagen (`"image"`).
   - Si la extension no es reconocida, se asume imagen para permitir que el flujo de OCR la procese.

2. **Extraccion de texto (`extract/text_extractor.py`)**
   - Para PDFs:
     - Se usa `extract_pdf_text`, que primero intenta leer texto con `pdfminer`.
     - Si el texto resultante es demasiado corto, se convierte cada pagina a imagen (`pdf2image`) y se extrae texto con Tesseract (modo OCR).
     - El parametro `PDF_OCR_MAX_PAGES` de `config/settings.py` limita el numero de paginas que se mandan a OCR.
   - Para imagenes (o formatos tratados como tal):
     - `extract_image_text` abre la imagen con Pillow y pasa el bitmap a `_ocr_page`, que aplica un preprocesado binario y llama a Tesseract con el modelo de idioma ingles (`lang="eng"`).
   - Cada pagina se representa como `PageText`, con metodos para unir lineas (`join_pages`).

3. **Construccion del prompt (`llm/prompts.py`)**
   - `build_messages` arma los mensajes `system` y `user` que consumira Groq.
   - Incluye el esquema `invoice_v1`, las categorias validas y reglas sobre montos, fechas y advertencias.

4. **Invocacion al LLM (`llm/groq_client.py`)**
   - `call_groq` realiza la llamada HTTP a la API de Groq con reintentos exponenciales.
   - Si falta la clave `GROQ_API_KEY`, se usa `_generate_stub_response` para producir un JSON sintetico que sigue el contrato.

5. **Validacion y normalizacion (`llm/validator.py` y `service/pipeline.py`)**
   - `parse_response` limpia el texto devuelto por Groq y valida el JSON contra `schema/invoice_v1.py` (modelos Pydantic).
   - `_parse_and_normalize` ajusta campos faltantes, resuelve la moneda con `_resolve_currency`, normaliza items y agrega advertencias si la suma de lineas y el total difieren mas del 1%.
   - `category/classifier.py` aporta categorias por reglas si el LLM no las define. Usa listas inglesas en `category/rules.py` y pistas por proveedor (`VENDOR_HINTS`).

6. **Persistencia (`storage/db.py`)**
   - `save_document` guarda el JSON, el texto original y los campos clave en SQLite (via SQLAlchemy) y registra cada item.
   - `get_document_by_hash` habilita cacheo por hash para evitar reprocesar archivos identicos.

## Configuracion y utilidades clave

- `config/settings.py` carga variables de entorno (opcional `.env`) y prepara rutas (`CACHE_DIR`, `UPLOAD_DIR`, `PROCESSED_DIR`, `DEFAULT_DB_PATH`). Tambien expone los parametros de Groq y limites de OCR.
- `utils/files.py` aporta `compute_file_hash`, que lee el archivo por bloques para generar el hash SHA-256 sin consumir memoria excesiva.
- `datasets/donut_loader.py` contiene un helper para bajar muestras de `katanaml-org/invoices-donut-data-v1` y no impacta el pipeline en produccion.

## Resumen del flujo segun el tipo de archivo

| Tipo de entrada | Extraccion inicial | Fallback | Resultado |
|-----------------|--------------------|----------|-----------|
| PDF             | `extract_pdf_text` via pdfminer | OCR pagina a pagina con Tesseract si el texto es escaso | Coleccion de `PageText` con contenido por pagina |
| Imagen (jpg, png, etc.) | `extract_image_text` (OCR inmediato) | No aplica, se usa un unico paso | `PageText` unico con el texto reconocido |

En ambos casos, el texto extraido se une mediante `join_pages`, se construye el prompt, se invoca a Groq y se normaliza la respuesta antes de guardarla en la base. El pipeline garantiza que todos los registros persistan con fechas ISO, montos en centavos y categorias estandarizadas.
