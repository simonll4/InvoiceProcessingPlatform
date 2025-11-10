# OCR-LLM Pipeline

Sistema para extraer campos estructurados de facturas y recibos combinando `pdfminer.six`, Tesseract OCR y Groq (endpoint OpenAI-compatible).
## Características principales
- Soporta PDF e imágenes (JPG/PNG/BMP) con detección automática.
- Extrae texto con `pdfminer.six` y, si es insuficiente, rasteriza y aplica Tesseract (`eng+spa`).
- El extractor LLM devuelve JSON válido contra el contrato `invoice_v1`.
- Clasifica ítems por palabras clave y persiste cache/auditoría en SQLite (`data/app.db`).
- La API FastAPI sirve la UI estática directamente (sin Nginx adicional).

## Quickstart (Docker Compose)
```bash
cp configs/env/.env.example configs/env/.env  # configura tus GROQ_*
docker compose -f infra/docker-compose.yml up -d --build
# UI:  http://localhost:8001/
# API: http://localhost:8001/api/health
```
> **Nota**: si `GROQ_API_KEY` está vacío el servicio responde con un extractor heurístico de baja fidelidad. Define la variable para habilitar Groq real.

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
## CLI incluida
```bash
python -m scripts.pipeline_cli extract datasets/donut_samples/donut_train_0004.png --out out.json
python -m scripts.pipeline_cli batch datasets/donut_samples --pattern "*.png"
python -m scripts.pipeline_cli test-samples
python -m scripts.pipeline_cli fetch-donut --split train --limit 10 --out datasets/donut_samples
```
## API
- `GET /` devuelve la SPA estática.
- `GET /api/health` health check.
- `GET /api/warmup` ping ligero para calentar el servicio.
- `POST /api/extract` acepta `multipart/form-data` con `file` (≤10 MB).

## Variables de entorno relevantes
| Variable | Descripción | Default |
| --- | --- | --- |
| `GROQ_API_KEY` | Token Groq para el extractor real. | `""` |
| `GROQ_API_BASE` | Endpoint Groq OpenAI-compatible. | `https://api.groq.com/openai/v1` |
| `GROQ_MODEL` | Modelo Groq a usar. | `llama-3.3-70b-versatile` |
| `GROQ_ALLOW_STUB` | Permite fallback heurístico sin API key. | `true` |
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
4. **LLM**: invoca Groq (o stub) y valida JSON con Pydantic.
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
  pipeline/       # Pipeline OCR + Groq + persistencia
configs/env/      # Variables de entorno
infra/            # docker-compose.yml y orquestación
scripts/          # CLI Typer
data/             # app.db + uploads/processed
README.md         # Descripción general
START.md          # Guía rápida
```

## Próximos pasos
- Revisa `START.md` para checklist de despliegue.
- Ejecuta `python -m scripts.pipeline_cli test-samples` para validar con ejemplos.
- Configura `GROQ_API_KEY` antes de despliegues serios.
