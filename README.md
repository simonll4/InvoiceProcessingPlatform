## OCR-LLM Pipeline

Repositorio para el pipeline de extracción de datos con OCR + Groq opcional.

### Highlights
- API FastAPI + UI servida como estático en `services/api` (sin Nginx aparte).
- Pipeline modular (`services/pipeline/service/pipeline.py`) con OCR pdfminer+Tesseract y extracción JSON `invoice_v1` vía Groq.
- Persistencia SQLite alojada en `data/app.db`, uploads centralizados en `data/uploads/`.
- CLI (`python -m scripts.pipeline_cli`) con comandos `extract`, `batch`, `test-samples`, `fetch-donut`.

### Documentación
- Guía completa, variables de entorno y flujo del pipeline: [docs/README.md](docs/README.md)
- Guía rápida paso a paso: [START.md](START.md)

### Comandos comunes
```bash
docker compose -f infra/docker-compose.yml up -d --build
python -m scripts.pipeline_cli extract datasets/donut_samples/donut_train_0004.png --out out.json
```
