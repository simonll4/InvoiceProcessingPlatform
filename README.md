# Invoice Processing Platform

Plataforma modular para digitalizar facturas con OCR + LLM y permitir consultas conversacionales sobre la información procesada. Está compuesta por microservicios Python/Node/NGINX coordinados mediante Docker Compose y una base SQLite compartida.

## Visión general del sistema
1. **Ingesta**: el servicio `ocr-pipeline-python` recibe PDF/imagenes, extrae texto, invoca al LLM para generar el JSON `invoice_v1`, normaliza y persiste los resultados en SQLite.
2. **Consulta conversacional**: `invoice-agent-python` expone un agente LangGraph que convierte preguntas en SQL seguro y consulta los datos mediante el servidor MCP.
3. **Acceso a datos**: `sqlite-mcp-server` ofrece herramientas MCP de solo lectura sobre la base, actuando como firewall entre agentes y SQLite.
4. **Experiencia de usuario**: `web-ui` sirve la interfaz web y funciona como reverse proxy hacia los servicios anteriores.

```
UI (web-ui) → pipeline-api (OCR) → SQLite
            ↘ invoice-agent → MCP server → SQLite
```

## Servicios
| Servicio | Descripción | Tecnologías |
| --- | --- | --- |
| [`services/ocr-pipeline-python`](services/ocr-pipeline-python/README.md) | API FastAPI que procesa documentos y guarda facturas estructuradas. | FastAPI, pdfminer, Tesseract, Groq, SQLAlchemy |
| [`services/invoice-agent-python`](services/invoice-agent-python/README.md) | Agente conversacional que responde preguntas en español sobre las facturas persistidas. | FastAPI, LangGraph, Groq, MCP |
| [`services/sqlite-mcp-server`](services/sqlite-mcp-server/README.md) | Servidor MCP Node.js que expone la base SQLite en modo solo lectura para los agentes. | Express, better-sqlite3, MCP SDK |
| [`services/web-ui`](services/web-ui/README.md) | Frontend estático + reverse proxy para subir facturas y chatear con el agente. | Nginx, HTML/CSS/JS |

Cada README explica qué hace el servicio y su stack. Los detalles de diseño/arquitectura se documentan en `docs/ARCHITECTURE.md` dentro de cada carpeta.

## Inicio rápido
```bash
cd pipeline-python
# Copiar archivos de ejemplo de variables de entorno para cada servicio
cp services/ocr-pipeline-python/.env.example services/ocr-pipeline-python/.env
cp services/invoice-agent-python/.env.example services/invoice-agent-python/.env
cp services/sqlite-mcp-server/.env.example services/sqlite-mcp-server/.env
# Completar las claves API de LLM en los archivos .env correspondientes
docker compose up -d
```
- UI: `http://localhost:7000`
- Pipeline API: `http://localhost:7001`
- Agente: `http://localhost:7003`

## Datos y dependencias
- Los servicios comparten `./data` (configurable) para almacenar la base SQLite y archivos subidos.
- Se requieren paquetes del sistema (`poppler-utils`, `tesseract-ocr`) cuando se ejecuta el pipeline fuera de Docker.
- Las claves del LLM se definen en los archivos `.env` de cada servicio (`services/ocr-pipeline-python/.env` y `services/invoice-agent-python/.env`).

## Estado del proyecto
- Pipeline OCR: estable para pruebas con documentos reales.
- Agente: MVP con validación de SQL y memoria corta.
- MCP server + Web UI: funcionales para entornos de laboratorio.
