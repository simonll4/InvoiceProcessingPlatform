# Invoice Agent Service

Servicio Python que expone un agente conversacional para consultar facturas procesadas. Toma preguntas en español, induce SQL seguro a partir del esquema de la base, ejecuta la consulta a través del servidor MCP y devuelve respuestas en lenguaje natural manteniendo contexto entre turnos.

## Capacidades clave
- Comprensión de preguntas de negocio sobre facturas (totales, proveedores, filtros, fechas).
- Traducción pregunta → SQL con LangGraph y validación antes de ejecutar.
- Acceso indirecto a SQLite mediante MCP para aislar el agente de la base.
- Memoria conversacional en RAM por `session_id` para follow-ups coherentes.
- Respuestas finales en español con manejo de errores amigable.

## Stack principal
| Capa | Tecnologías |
| --- | --- |
| API | FastAPI 0.115, Uvicorn |
| Razonamiento | LangGraph (7 nodos), LangChain |
| LLM | Groq `llama-3.3-70b-versatile` vía `langchain-groq` |
| Datos | SQLite consultado vía `sqlite-mcp-server` |
| Utilidades | Loguru, Pydantic v2, httpx |

## Interfaces expuestas
- `POST /ask`: recibe `{session_id, question}` y retorna `{answer, error_code, error_message}`.
- `GET /health`: indica si el proceso FastAPI está vivo.

## Ejecución rápida
```bash
# Desde la raíz del repo
docker compose up invoice-agent-api
```

Para desarrollo local:
```bash
cd services/invoice-agent-python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # completa tu INVOICE_AGENT_GROQ_API_KEY
uvicorn src.main:app --host 0.0.0.0 --port 7003 --reload
```

## Variables de entorno principales
| Variable | Descripción | Ejemplo |
| --- | --- | --- |
| `INVOICE_AGENT_GROQ_API_KEY` | API key para Groq. | `gsk_xxx` |
| `INVOICE_AGENT_GROQ_MODEL` | Modelo usado por LangGraph. | `llama-3.3-70b-versatile` |
| `INVOICE_AGENT_MCP_ENDPOINT` | URL del servidor MCP (ver servicio sqlite). | `http://mcp-sqlite:7002` |
| `INVOICE_AGENT_API_PORT` | Puerto FastAPI. | `7003` |
| `INVOICE_AGENT_MAX_HISTORY_TURNS` | Turns de memoria por sesión. | `5` |
| `INVOICE_AGENT_SQL_MAX_ROWS` | Máximo de filas devueltas por consulta. | `200` |

## Documentación
- `docs/ARCHITECTURE.md`: diseño del grafo LangGraph, nodos, flujo de datos y decisiones relevantes.
