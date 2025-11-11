## OCR-LLM Pipeline

Repositorio para el pipeline de extracción de datos con OCR + Groq opcional.

### Highlights
- API FastAPI + UI servida como estático en `services/api` (sin Nginx aparte).
- Pipeline modular (`services/pipeline/service/pipeline.py`) con OCR pdfminer+Tesseract y extracción JSON `invoice_v1` vía Groq.
- Persistencia SQLite alojada en `data/app.db`, uploads centralizados en `data/uploads/`.
- Procesamiento manual sencillo importando `run_pipeline` desde tus propios scripts o REPL.

### Documentación
- Guía completa, variables de entorno y flujo del pipeline: [docs/README.md](docs/README.md)
- Guía rápida paso a paso: [START.md](START.md)

### Comandos comunes
```bash
docker compose -f infra/docker-compose.yml up -d --build
python - <<'PY'
from services.pipeline.service.pipeline import run_pipeline
from pprint import pprint

pprint(run_pipeline("datasets/donut_samples/donut_train_0004.png"))
PY
```
