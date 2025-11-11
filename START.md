# 🚀 Cómo empezar

Esta hoja rápida resume los pasos mínimos. Para más detalles consulta `docs/README.md`.

## 1. Docker Compose (recomendado)

```bash
cp configs/env/.env.example configs/env/.env  # Ajusta tus GROQ_*
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml ps
```

URLs por defecto:
- UI + API: http://localhost:8001/
- Healthcheck: http://localhost:8001/api/health
- Swagger: http://localhost:8001/docs

Comandos útiles:
```bash
docker compose -f infra/docker-compose.yml logs -f api
docker compose -f infra/docker-compose.yml restart api
docker compose -f infra/docker-compose.yml down
```

## 2. Desarrollo local (sin Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

cp configs/env/.env.example configs/env/.env
python -m services.api.app.main  # UI + API en http://localhost:8000
```

La UI estática se sirve desde FastAPI, así que no se necesita Nginx ni un proyecto `ui/` aparte.

## 3. Procesar el pipeline desde Python

Aunque se retiró la CLI, aún puedes probar el pipeline directamente desde Python:

```bash
python - <<'PY'
from services.pipeline.service.pipeline import run_pipeline
from pprint import pprint

result = run_pipeline("datasets/donut_samples/donut_train_0004.png")
pprint(result)
PY
```
> Asegúrate de tener muestras en `datasets/donut_samples/` (usa tu propio dataset o sube archivos desde la UI).  
> Para descargar ejemplos del dataset Donut rápidamente:
> ```bash
> python - <<'PY'
> from services.pipeline.datasets.donut_loader import download_donut_samples
> download_donut_samples(out_dir="datasets/donut_samples", split="train", limit=10)
> PY
> ```

## 4. Chequeos rápidos

- `curl http://localhost:8001` verifica la UI.
- `curl http://localhost:8001/api/health` comprueba la API.
- `docker compose -f infra/docker-compose.yml logs -f api` muestra el progreso del primer OCR (descarga de ~150 MB).

## 5. Troubleshooting común

- **Puertos en uso**: ejecuta `sudo lsof -i :8001` y modifica el mapeo en `infra/docker-compose.yml`.
- **Credenciales Groq**: define `GROQ_API_KEY` en `configs/env/.env`; sin clave sólo se usa el stub heurístico.
- **Dependencias OCR**: instala `poppler-utils` y `tesseract-ocr` (eng+spa) antes de procesar PDFs en entornos locales.

## 6. Qué sigue

1. Abre la UI (`http://localhost:8001`) y sube un PDF/imagen de prueba.
2. Revisa `docs/README.md` para entender el flujo completo y las variables disponibles.
3. Automatiza llamadas batch conectándote al endpoint `/api/extract` o creando tus propios scripts que importen `run_pipeline`.

---

Pipeline principal: `services/pipeline/service/pipeline.py`.  
Persistencia: SQLite en `data/app.db` (se crea automáticamente).
