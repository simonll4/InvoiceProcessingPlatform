# Invoice Agent Service — Arquitectura y Diseño

## Propósito del servicio
Agente conversacional especializado en responder preguntas sobre las facturas almacenadas en la plataforma. Su responsabilidad es convertir la consulta del usuario en SQL seguro, ejecutar la consulta a través del servidor MCP de SQLite y entregar la respuesta en español con contexto conversacional. No escribe en la base de datos ni realiza cálculos fuera de la información persistida.

## Vista general
- **Interfaz**: FastAPI expone `/ask` y `/health`.
- **Orquestación**: LangGraph con 7 nodos secuenciales más un manejador de errores.
- **LLM**: Groq `llama-3.3-70b-versatile` vía LangChain para generar SQL y prosa.
- **Memoria**: `MemoryStore` en RAM (máx. 5 turnos por sesión) almacena `{question, answer, sql}`.
- **Datos**: Todo acceso pasa por `sqlite-mcp-server`, que entrega esquema y ejecuta SELECTs con límite de filas.
- **Observabilidad**: Loguru centraliza logs estructurados y métricas mínimas.

```
Usuario → FastAPI (/ask) → Grafo LangGraph → (Groq LLM + MCP server) → SQLite
                                        ↘ historial en MemoryStore ↙
```

## Flujo del grafo LangGraph
1. **ReceiveQuestion**: recupera historial de la memoria e inicializa el estado.
2. **EnsureSchema**: invoca `sqlite_get_schema` del MCP y cachea el resultado en el estado.
3. **GenerateSQL**: prompt especializado (system + user) genera un SELECT ajustado al esquema.
4. **ValidateSQL**: detiene keywords peligrosas, fuerza `LIMIT` y respeta `sql_max_rows`.
5. **ExecuteSQLViaMCP**: llama al servidor MCP con `sqlite_run_select` y adjunta filas en el estado.
6. **GenerateAnswer**: produce una respuesta en español con explicación textual de los resultados.
7. **HandleError**: nodo global que atrapa excepciones y devuelve `error_code/error_message` homogéneos.

Cada nodo opera sobre `InvoiceAgentState`, un `TypedDict` que contiene `session_id`, `question`, `history`, `schema`, `sql`, `result`, `answer` y campos de error. Tras ejecutar el grafo se invoca `save_to_memory()` para persistir la nueva interacción.

## Módulos principales
### `src/main.py`
Define la aplicación FastAPI, valida entradas y transforma el estado final del grafo en la respuesta HTTP.

### `src/di.py`
Inicializa singletons (`ChatGroq`, `MCPClient`, `MemoryStore`, grafo compilado) usando `lru_cache`. Esto evita recrear conexiones y permite ajustar dependencias durante pruebas.

### `src/agent/`
- `graph.py`: construye y compila el `StateGraph`, contiene helper `save_to_memory`.
- `state.py`: tipado del estado compartido.
- `nodes/`: implementación de los siete nodos mencionados, cada uno con validaciones propias (p. ej. `validate_sql` bloquea multi-statements y añade límites).

### `src/core/memory.py`
Estructura ligera con `ConversationTurn` y `MemoryStore`. Incluye trim automático para mantener los últimos N turnos.

### `src/integrations/mcp_client.py`
Cliente HTTP para el servidor MCP. Construye payloads JSON-RPC, interpreta respuestas (`content` vs `structuredContent`) y homogeneiza errores.

### `src/api/schemas.py`
Modelos Pydantic v2 para requests/responses. Garantizan que `session_id` sea obligatorio y que la respuesta siempre contenga `answer` aunque haya errores.

## Integraciones externas
- **Groq**: `ChatGroq` maneja reintentos y límites suaves; temperatura fija en 0.0 para SQL determinístico.
- **SQLite MCP Server**: expone herramientas `sqlite_get_schema` y `sqlite_run_select`. La integración valida cada respuesta y transforma errores de validación en `error_code="query_validation_failed"`.

## Decisiones clave
- **MCP obligatorio**: el agente nunca abre la base de datos directamente; esto facilita aislar privilegios en producción.
- **SQL únicamente lectura**: el validador descarta cualquier comando que no sea SELECT y limita filas para proteger el agente y al MCP.
- **Memoria en RAM**: suficiente para el alcance actual; permite mantener coherencia de conversación sin persistencia adicional.
- **Prompts bifásicos**: se usan prompts distintos para generar SQL y para redactar la respuesta final, minimizando alucinaciones.
- **Errores en español**: todos los mensajes enviados al usuario se traducen para mantener UX consistente con la UI.

## Operación y configuración
- **Puertos**: por defecto 7003/tcp expuesto como `invoice-agent-api` en `docker-compose`.
- **Logs**: `LOGURU_LEVEL` ajusta verbosidad; se recomienda `INFO` en producción y `DEBUG` para tuning de prompts.
- **Parámetros relevantes**:
  - `INVOICE_AGENT_MAX_HISTORY_TURNS`: memoria por sesión.
  - `INVOICE_AGENT_SQL_MAX_ROWS`: límite duro de filas retornadas por MCP.
  - `INVOICE_AGENT_MCP_TIMEOUT`: tiempo máximo (s) para llamadas RPC.
- **Salud**: `/health` responde siempre que haya arrancado FastAPI; fallas aguas abajo se reflejan en `/ask`.

## Riesgos y próximas mejoras
- Persistir memoria en Redis para soportar múltiples réplicas.
- Añadir tracing de LangGraph para depurar prompts.
- Cachear el esquema en memoria con TTL para reducir llamadas al MCP cuando hay muchas preguntas en paralelo.
