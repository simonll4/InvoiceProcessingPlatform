# SQLite MCP Server

Servicio Node.js que expone una base SQLite en modo solo-lectura usando el protocolo Model Context Protocol (MCP). Provee dos herramientas (`sqlite_get_schema` y `sqlite_run_select`) consumidas por el agente de facturas para inspeccionar el esquema y ejecutar consultas SELECT seguras con límite de filas.

## Capacidades clave
- Endpoints HTTP (`/mcp`, `/health`) empaquetados en un servidor Express.
- Conexión `better-sqlite3` en modo `readonly` con pragmas seguros y cierre explícito.
- Validación defensiva: solo acepta consultas que comiencen con `SELECT`, bloquea keywords peligrosas y múltiples sentencias.
- Límite configurable de filas (`MAX_ROWS`) aplicado en el servidor antes de serializar los resultados.
- Respuestas MCP con `content` y `structuredContent` para facilitar parsing en clientes LLM.

## Stack principal
| Capa | Tecnologías |
| --- | --- |
| Runtime | Node.js 20, TypeScript |
| HTTP | Express + `@modelcontextprotocol/sdk` transport HTTP streamable |
| DB | better-sqlite3 (readonly) |
| Configuración | dotenv |
| Validación | zod |

## Ejecución rápida
```bash
cd services/sqlite-mcp-server
npm install
npm run build
PORT=7002 APP_DB_PATH=/app/data/app.db node dist/index.js
```
En Docker Compose el servicio se expone como `mcp-sqlite:7002` y comparte volumen `/app/data` con el pipeline.

## Variables de entorno
| Variable | Descripción | Default |
| --- | --- | --- |
| `APP_DB_PATH` | Ruta absoluta del archivo SQLite. | `/app/data/app.db` |
| `PORT` | Puerto HTTP escuchando `/mcp`. | `3000` |
| `MAX_ROWS` | Máximo de filas retornadas por consulta. | `200` |

## Documentación
- `docs/ARCHITECTURE.md`: diseño detallado del servidor, módulos y decisiones de seguridad.
