# OCR Pipeline Service

Servicio FastAPI que expone el pipeline OCR + LLM para extraer facturas estructuradas (`invoice_v1`) a partir de PDF o imágenes. Está pensado como motor de ingesta para el resto de la plataforma: procesa el archivo, aplica validaciones/normalizaciones y persiste los resultados en SQLite para consultas posteriores.

## Capacidades clave
- Ingesta segura de archivos (PDF/JPG/PNG/BMP) con control de concurrencia y validación de tipo.
- Extracción híbrida de texto: pdfminer para PDFs y Tesseract como fallback cuando la señal es baja.
- Prompts estrictos y validadores Pydantic para garantizar JSON consistente.
- Normalización de montos, clasificación de ítems y caché basada en hash para evitar gastos de LLM repetidos.
- API lista para Docker/Kubernetes con healthcheck ligero y almacenamiento local en `data/`.

## Stack principal
| Capa | Tecnologías |
| --- | --- |
| API | FastAPI, Uvicorn, Pydantic v2 |
| OCR | pdfminer.six, pytesseract, Pillow |
| LLM | Groq/OpenAI compatibles vía cliente propio |
| Persistencia | SQLite + SQLAlchemy |
| Utilidades | Loguru, python-dotenv |

## Uso rápido
```bash
cd pipeline-python
cp services/ocr-pipeline-python/.env.example services/ocr-pipeline-python/.env  # completa PIPELINE_LLM_API_KEY
API_HOST_PORT=7001 docker compose up -d pipeline-api
```
- API: `http://localhost:7001`
- Docs: `http://localhost:7001/docs`
- Health: `http://localhost:7001/api/health`

Para desarrollo sin Docker:
```bash
cd services/ocr-pipeline-python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000
```

## Documentación
- `docs/ARCHITECTURE.md`: diseño del pipeline, módulos y decisiones.
