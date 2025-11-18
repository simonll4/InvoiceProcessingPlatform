# Web UI Service

UI estática servida por Nginx que ofrece dos flujos: subir facturas al pipeline OCR y conversar con el agente de facturas. Actúa como frontdoor del sistema cuando se levanta `docker compose up web-ui` y reenvía el tráfico a los microservicios backend.

## Capacidades clave
- Drag & drop para subir PDFs/imagenes y visualizar el JSON estructurado devuelto por el pipeline.
- Visualización amigable de totales, ítems, advertencias y JSON completo.
- Chat integrado con panel de sugerencias, manejo client-side del `session_id` y llamadas al agente (`/api/agent/ask`).
- Manejo de errores frecuentes (rate limits, archivos grandes, OCR pobre) con mensajes en español.
- Servidor Nginx que actúa como reverse proxy a `pipeline-api`, `invoice-agent-api` y expone Swagger/health heredado del pipeline.

## Stack principal
| Capa | Tecnologías |
| --- | --- |
| Frontend | HTML + CSS + Vanilla JS modular (`static/app.js`) |
| Servidor | Nginx Alpine con configuración personalizada (`nginx.conf`) |
| Integraciones | Fetch API hacia `/api/pipeline/*` y `/api/agent/*` |

## Uso rápido
```bash
cd pipeline-python
docker compose up -d web-ui
# UI: http://localhost:7000
```
El contenedor copia `static/` a `/usr/share/nginx/html` y aplica `nginx.conf`, que ya contiene los proxies internos hacia los servicios.

## Documentación
- `docs/ARCHITECTURE.md`: arquitectura del frontend estático y del reverse-proxy.
