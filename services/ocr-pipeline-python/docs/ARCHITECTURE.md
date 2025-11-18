# OCR Pipeline Service — Arquitectura y Diseño

## Propósito
Microservicio FastAPI que recibe PDFs o imágenes de facturas y devuelve un payload JSON compatible con `invoice_v1`. Combina extracción híbrida de texto (pdfminer + Tesseract), prompts estrictos para Groq/OpenAI y un módulo de normalización/validación antes de persistir en SQLite.

## Vista general
- **Interfaz HTTP**: `POST /api/pipeline/extract` (procesa archivos) y `GET /api/health` (monitorización).
- **Orquestación**: `src/pipeline/service/orchestrator.py` coordina 7 pasos desde la subida hasta la caché.
- **Motor LLM**: Groq `llama-3.3-70b-versatile`, accesible a través de `langchain-groq` y un rate limiter propio.
- **OCR / extracción**: pdfminer para PDFs + fallback a Tesseract para documentos con poco texto o imágenes.
- **Persistencia**: SQLite vía SQLAlchemy, usada como caché de resultados y almacenamiento histórico.
- **Infraestructura**: Contenedor único (python:3.11) con dependencias del sistema (`poppler`, `tesseract` recomendado para ejecución local).

```
Upload HTTP → FastAPI → (guardar archivo) → Orquestador →
  ├─ Ingest/Detect source → Extract text (pdfminer / Tesseract)
  ├─ Construcción de prompt → LLM (Groq)
  ├─ Normalización + validación → SQLite (persistencia/cache)
  └─ Respuesta JSON invoice_v1
```

## Flujo detallado del pipeline
1. **Upload y validación**: `api/pipeline.py` limita tipos MIME (PDF/JPG/PNG/BMP) y aplica un semáforo configurable (`MAX_CONCURRENCY`).
2. **Hash + caché**: `compute_file_hash()` genera SHA-256; si existe en `invoices.file_hash`, se devuelve inmediatamente.
3. **Detección de fuente**: `ingest/loader.detect_source` identifica si procesar como PDF o imagen.
4. **Extracción de texto**:
   - PDFs → `extract_pdf_text` con `PDF_OCR_MAX_PAGES` (default 5) y rasterizado a `PDF_OCR_DPI` si hay fallback.
   - Imágenes → `extract_image_text` (Tesseract, soporte multi-idioma si está instalado el paquete).
5. **Preparación de prompt**: `llm/prompts.build_messages` compacta texto (`validators.compact_prompt_text`) y arma instrucciones para JSON estricto.
6. **LLM call**: `llm/groq_client.call_llm` aplica rate limits (RPM/RPD/TPM/TPD), reintentos y stub opcional si falta API key.
7. **Parseo y validación**: `llm/validator.parse_response` alimenta modelos `InvoiceV1`; luego `normalizer.py` corrige montos, resuelve moneda y ajusta descuentos.
8. **Procesamiento de ítems**: `item_processor.py` clasifica, agrupa descripciones y filtra warnings falsos.
9. **Persistencia**: `storage/db.py` guarda JSON completo + tablas normalizadas (`invoices`, `items`) y mantiene caché.
10. **Respuesta**: se devuelve `dict` estructurado con `schema_version`, `invoice`, `items`, `notes`.

## Módulos principales
- **`src/api/`**: routers FastAPI. `pipeline.py` gestiona uploads, `health.py` entrega estado básico.
- **`pipeline/config/settings.py`**: carga `.env` desde el directorio del servicio y resuelve rutas (uploads, DB). También expone constantes de OCR y rate limit.
- **`pipeline/extract/`**: abstracción de OCR/pdfminer. Devuelve `List[PageText]` para alimentar al LLM.
- **`pipeline/llm/`**: cliente Groq, prompts, validadores, rate limiter y utilidades de texto/moneda.
- **`pipeline/service/`**: capa orquestadora (`orchestrator`, `normalizer`, `item_processor`, `validators`).
- **`pipeline/storage/`**: modelos SQLAlchemy + helpers `get_document_by_hash` y `save_document`.
- **`pipeline/utils/`**: utilidades para hashing/archivos.

## Datos y persistencia
- **Esquema `invoice_v1`**: `Invoice`, `Item`, `Notes` definidos con Pydantic.
- **SQLite**: archivo configurable mediante `DB_URL` o `DB_PATH`. Guarda JSON completo (para rehidratación) y tablas relacionales para analítica.
- **Caché de resultados**: la combinación hash + raw_json evita usar tokens del LLM cuando se sube dos veces la misma factura.

## Decisiones importantes
- **Extracción híbrida**: pdfminer se usa primero porque conserva estructura; si hay poco texto (`TEXT_MIN_LENGTH`) se activa OCR para no depender del LLM.
- **Prompts estrictos**: instrucciones obligan a responder solo JSON y contemplan formatos europeos de números. Se descartan bloques que no sean JSON válido.
- **Normalización defensiva**: varias capas corrigen errores comunes del LLM (montos en distintas escalas, descuentos fantasma, ítems describiendo totales).
- **Límites conservadores**: `MAX_CONCURRENCY=1` y rate limits al 80 % de lo permitido para no saturar cuentas gratuitas.
- **Persistencia idempotente**: mantener el archivo subido tras éxito permite reproducibilidad/auditoría; si falla, se borra automáticamente.

## Configuración relevante
| Variable | Descripción | Default |
| --- | --- | --- |
| `PIPELINE_LLM_API_KEY` | Clave del LLM. | `""` (stub opcional) |
| `PIPELINE_LLM_MODEL` | Modelo Groq/OpenAI. | `llama-3.3-70b-versatile` |
| `PIPELINE_LLM_ALLOW_STUB` | Respuesta simulada sin API key. | `false` |
| `RATE_LIMIT_RPM/RPD/TPM/TPD` | Límites de peticiones y tokens. | `24/11500/4800/400000` |
| `PDF_OCR_DPI` | Resolución al rasterizar. | `300` |
| `PDF_OCR_MAX_PAGES` | Máx. páginas a procesar. | `5` |
| `TEXT_MIN_LENGTH` | Caracteres mínimos tras OCR. | `120` |
| `UPLOAD_DIR` | Carpeta temporal para uploads. | `data/uploads` |
| `DB_URL` | Cadena SQLAlchemy. | `sqlite:///data/app.db` |
| `MAX_CONCURRENCY` | Semáforo de requests en paralelo. | `1` |

## Operación
- **Docker Compose**: servicio `pipeline-api` escucha en `:8000` y se expone detrás de `web-ui`.
- **Dependencias del sistema**: en local instalar `poppler-utils` y `tesseract-ocr` (idiomas en/ es) para resultados consistentes.
- **Debugging**: logs clave (`Processing document`, `Cache hit`, `LLM returned invalid response`). `clear_cache.py` en la raíz ayuda a limpiar la base si se cambian prompts.
- **Pruebas**: `tests/` contiene lotes básicos de regresión, ejecutables con `pytest` una vez configuradas dependencias del sistema.

## Próximos pasos sugeridos
- Instrumentar métricas (tiempos de OCR, tokens usados) para detectar cuellos de botella.
- Habilitar `apply_summary_overrides` una vez que el parser soporte formatos numéricos con espacios.
- Añadir colas/background jobs para procesar documentos largos sin bloquear el request HTTP.
