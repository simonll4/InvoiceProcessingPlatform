# OCR-LLM Pipeline

Sistema para extraer campos estructurados de facturas y recibos combinando `pdfminer.six`, Tesseract OCR y Groq (endpoint OpenAI-compatible) para la extracción LLM.
## Características principales
- Soporta PDF e imágenes (JPG/PNG/BMP) con detección automática.
- Extrae texto con `pdfminer.six` y, si es insuficiente, rasteriza y aplica Tesseract (`eng+spa`).
- El extractor LLM devuelve JSON válido contra el contrato `invoice_v1`.
- Clasifica ítems por palabras clave y persiste cache/auditoría en SQLite (`data/app.db`).
- La API FastAPI sirve la UI estática directamente (sin Nginx adicional).

## Quickstart (Docker Compose)
```bash
cp configs/env/.env.example configs/env/.env  # incluye Groq para el pipeline y el assistant
docker compose -f infra/docker-compose.yml up -d --build
# UI:  http://localhost:8001/
# API: http://localhost:8001/api/health
```
> **Notas**:
> - Debes definir `PIPELINE_LLM_API_KEY` o `LLM_API_KEY` con tu token de Groq para que el extractor y el asistente funcionen.

### Probar con curl
```bash
curl -F file=@datasets/donut_samples/donut_train_0004.png http://localhost:8001/api/extract
```
## Uso local sin Docker
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp configs/env/.env.example configs/env/.env
python -m services.api.app.main  # API + UI en http://localhost:8000
```
## Ejecutar el pipeline desde Python
```bash
python - <<'PY'
from services.pipeline.service.pipeline import run_pipeline
from pprint import pprint

sample = "datasets/donut_samples/donut_train_0004.png"
pprint(run_pipeline(sample))
PY
```

## Descarga rápida de samples Donut
```bash
python - <<'PY'
from services.pipeline.datasets.donut_loader import download_donut_samples

download_donut_samples(out_dir="datasets/donut_samples", split="train", limit=10)
PY
```
## API
- `GET /` devuelve la SPA estática.
- `GET /api/health` health check.
- `GET /api/warmup` ping ligero para calentar el servicio.
- `POST /api/extract` acepta `multipart/form-data` con `file` (≤10 MB).

## MCP oficial

El servidor MCP nativo usa el SDK `mcp` y se monta automáticamente dentro de la misma API.

- **Transport HTTP**: `http://localhost:8001/mcp` cuando corres `docker compose -f infra/docker-compose.yml ...`
- **Herramientas**: `execute_sql_query`, `get_invoice_by_id`, `search_invoices_by_vendor`, `get_top_vendors`, `search_by_text`, `get_invoices_by_date_range`, `get_database_schema`.
- **Cómo usarlo**: conecta cualquier cliente MCP (por ejemplo `mcp-cli` o integraciones de editores) a esa URL y obtendrás acceso de solo lectura a la base `app.db`.

## Variables de entorno relevantes
| Variable | Descripción | Default |
| --- | --- | --- |
| `PIPELINE_LLM_PROVIDER` | Proveedor LLM para el pipeline (Groq). | `groq` |
| `PIPELINE_LLM_API_BASE` | Endpoint OpenAI-compatible (Groq). | `https://api.groq.com/openai/v1` |
| `PIPELINE_LLM_MODEL` | Modelo Groq para extracción. | `llama-3.1-8b-instant` |
| `PIPELINE_LLM_API_KEY` | Token Groq obligatorio. | `""` |
| `PIPELINE_LLM_ALLOW_STUB` | Permite fallback heurístico en pipeline. | `false` |
| `LLM_API_BASE` | Endpoint Groq para el assistant. | `https://api.groq.com/openai/v1` |
| `LLM_MODEL` | Modelo Groq para el assistant. | `llama-3.1-8b-instant` |
| `LLM_API_KEY` | Token Groq del assistant (puede reutilizar el pipeline). | `""` |
| `RATE_LIMIT_RPM` | Límite de requests por minuto (Groq). | `24` |
| `RATE_LIMIT_RPD` | Límite de requests por día (Groq). | `11500` |
| `RATE_LIMIT_TPM` | Tokens por minuto (Groq). | `4800` |
| `RATE_LIMIT_TPD` | Tokens por día (Groq). | `400000` |
| `DEFAULT_CURRENCY` | Moneda fallback. | `UNK` |
| `PDF_OCR_DPI` | DPI al rasterizar PDF antes de OCR. | `300` |
| `PDF_OCR_MAX_PAGES` | Máx. páginas a rasterizar. | `5` |
| `TEXT_MIN_LENGTH` | Mínimos caracteres tras OCR para continuar. | `120` |
| `MAX_CONCURRENCY` | Semáforo del pipeline. | `1` |
| `DB_URL` | Cadena SQLAlchemy. | `sqlite:///data/app.db` |
| `DB_PATH` | Ruta SQLite (sólo si se requiere forzar). | `data/app.db` |
| `DB_DIR` | Carpeta raíz donde vive `app.db` (cuando no se usa `DB_PATH`). | `data/` |
| `UPLOAD_DIR` | Carpeta de archivos subidos. | `data/uploads` |
| `PROCESSED_DIR` | Carpeta de exportaciones. | `data/processed` |
## Flujo del pipeline
1. **Ingesta**: detecta tipo (PDF/imagen) y calcula hash SHA-256 para cache.
2. **Extracción**: usa `pdfminer.six`; si el texto es corto, rasteriza y aplica Tesseract.
3. **Prompt**: construye mensajes `system`/`user` con texto y esquema `invoice_v1`.
4. **LLM**: invoca Groq (OpenAI-compatible) y valida JSON con Pydantic.
5. **Normalización**: corrige moneda, clasifica ítems y agrega warnings si hay diferencias.
6. **Persistencia**: guarda texto/JSON en SQLite (`data/app.db`).
## Tips operativos
- Instala Poppler (`sudo apt install poppler-utils`) para soportar `pdf2image`.
- Ajusta `TEXT_MIN_LENGTH` para tickets muy cortos.
- El cache por hash evita reprocesar archivos repetidos.
## Estructura del repositorio (resumen)
```
services/
  api/            # FastAPI + UI estática
  pipeline/       # Pipeline OCR + LLM + persistencia
configs/env/      # Variables de entorno
infra/            # docker-compose.yml y orquestación
scripts/          # Espacio para entrypoints propios (sin CLI oficial)
data/             # app.db + uploads/processed
README.md         # Descripción general
START.md          # Guía rápida
```

## Próximos pasos
- Revisa `START.md` para checklist de despliegue.
- Ejecuta el snippet de Python anterior para validar con un sample local.
- Configura `GROQ_API_KEY` antes de despliegues serios.
