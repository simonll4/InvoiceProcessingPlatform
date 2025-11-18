# SQLite MCP Server — Arquitectura y Diseño

## Propósito
Proveer un punto de acceso MCP seguro y minimalista a la base SQLite generada por el pipeline de OCR. El servidor actúa como "firewall" entre los agentes LLM y los datos, permitiendo solo consultas de lectura con límites estrictos y auditables.

## Vista general
- **HTTP layer**: Express escucha `/mcp` y `/health`.
- **Transport MCP**: `StreamableHTTPServerTransport` del SDK oficial procesa las peticiones JSON-RPC sobre HTTP.
- **Capa DB**: `SqliteClient` envuelve `better-sqlite3` en modo read-only y expone helpers `getSchema()` y `runSelect()`.
- **Validación**: `zod` describe entrada/salida de cada herramienta MCP, mientras que validaciones adicionales aseguran que las consultas sean solo `SELECT`.

```
Cliente (agente) ─HTTP JSON-RPC→ Express (/mcp)
                                   └─> MCP Server (tools)
                                        ├─ sqlite_get_schema → SqliteClient.getSchema()
                                        └─ sqlite_run_select → validateSelectQuery() → SqliteClient.runSelect()
```

## Componentes
### `src/index.ts`
Arranca el servidor HTTP. Utiliza `config` para leer puerto y ruta de la base. Maneja errores de arranque (p. ej. archivo inexistente).

### `src/config.ts`
Carga `.env` usando `dotenv/config` y expone `APP_DB_PATH`, `PORT`, `MAX_ROWS`. Convierte tipos numéricos y marca variables obligatorias.

### `src/http/app.ts`
Construye la app Express:
- Inicializa una instancia compartida de `SqliteClient` (readonly).
- Crea el servidor MCP via `createMcpServer(db, MAX_ROWS)`.
- Expone `POST /mcp`: para cada request crea un `StreamableHTTPServerTransport`, conecta el MCP server y delega el manejo del payload JSON-RPC.
- Expone `GET /health`: retorna `{status: "ok"}` para pruebas rápidas.

### `src/mcp/server.ts`
Registra las herramientas MCP:
- `sqlite_get_schema`: devuelve un resumen estructurado de tablas/columnas más una versión textual para facilitar prompts.
- `sqlite_run_select`: valida la consulta (`SELECT` inicial, keywords prohibidas, un solo statement) y ejecuta hasta `MAX_ROWS`. Responde tanto en texto (preview) como en `structuredContent` con `rows` completos.
También define `renderSchemaText` y `validateSelectQuery`, reutilizables en otros entornos.

### `src/db/sqliteClient.ts`
Capa fina sobre `better-sqlite3`:
- `getSchema()`: usa `sqlite_master` + `PRAGMA table_info` para construir un objeto tipado.
- `runSelect(query, maxRows)`: ejecuta la consulta iterando manualmente y corta al llegar a `maxRows` para proteger memoria.
- Aplica `PRAGMA foreign_keys = ON` y abre la base en modo `readonly`.

## Decisiones de diseño
- **Read-only obligatorio**: el archivo se abre con `readonly: true` y no hay endpoints de escritura, lo que permite montar el volumen como `ro` en despliegues.
- **Validación temprana**: se verifica el SQL antes de tocar la base para devolver mensajes amigables al agente y evitar excepciones.
- **Límite en servidor**: incluso si el agente olvida agregar `LIMIT`, el servidor capea filas (`MAX_ROWS`) para proteger recursos.
- **Respuesta dual**: `content` textual ofrece contexto para humanos/logs y `structuredContent` entrega datos crudos para la IA.
- **Sin estado**: no se mantiene sesión; cualquier contenedor puede atender cualquier request mientras tenga acceso al archivo SQLite.

## Operación
- Arranque típico en Compose: `mcp-sqlite` escucha en `7002` y comparte volumen `./data:/app/data` con el pipeline.
- Logs: se imprimen a stdout (`console.log/error`); se recomienda envolver con un collector si se despliega en k8s.
- Health: `GET /health` sirve como probe para Compose/k8s.
- Actualizaciones: tras cambiar el código TypeScript ejecutar `npm run build` para regenerar `dist/` antes de publicar contenedor.

## Próximos pasos sugeridos
- Implementar cache del esquema para reducir lecturas de `sqlite_master` en escenarios de alta concurrencia.
- Añadir autenticación simple por token si se expone fuera de la red interna del cluster.
- Registrar métricas (tiempo de query, filas truncadas) para monitorear patrones de uso del agente.
