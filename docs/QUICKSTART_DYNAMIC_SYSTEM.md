# 🚀 Sistema Dinámico Basado en Schema - Guía Rápida

## ¿Qué cambió?

El sistema **ya no tiene respuestas preconfiguradas**. Ahora el LLM:

1. ✅ **Consulta el schema** de la DB cuando no está seguro de nombres de tablas/columnas
2. ✅ **Genera SQL dinámicamente** para cualquier pregunta
3. ✅ **Se limita al dominio facturas** - rechaza preguntas fuera del scope
4. ✅ **Aprende de sus errores** - si una SQL falla, recibe feedback y reintenta
- ✅ El schema incluye `invoice.discount_cents` (0 si no hay descuento) para capturar promociones de proveedores y mantener la relación `total = subtotal + tax - discount`.

## Archivos Modificados

### 1. `config.py`
- **Nueva variable:** `DISABLE_FALLBACK=True` (desactiva respuestas hardcodeadas)

### 2. `orchestrator.py`
- **RULE 0:** Sistema prompt que obliga al LLM a consultar schema primero
- **Gate de dominio:** Detecta y rechaza preguntas fuera de facturas
- **Sin fallback:** Ya no usa planes predefinidos para "item más caro", etc.
- **Tokens optimizados:** Planner usa 256 tokens, Summarizer usa 160

### 3. `mcp_server.py`
- **Sin cambios** (ya tenía todo lo necesario)

## Cómo Funciona

```
Usuario: "¿Cuál es el item más caro?"
    ↓
LLM Planner: "No estoy 100% seguro de los campos..."
    → Llama get_database_schema
    → Ve: items(line_total_cents, unit_price_cents, ...)
    → Genera: SELECT ... ORDER BY line_total_cents DESC LIMIT 1
    ↓
MCP ejecuta la SQL → Devuelve 1 fila
    ↓
LLM Summarizer: "El ítem más caro es X por $Y USD..."
```

## Ejemplos de Comportamiento

### ✅ Dentro del Dominio

**Pregunta:** "¿Cuánto gasté en total?"
- Consulta schema → Encuentra `invoices.total_cents`
- Genera: `SELECT SUM(total_cents) FROM invoices`
- Responde: "El gasto total es de $XXX USD."

**Pregunta:** "Los 5 proveedores principales"
- Consulta schema → Encuentra `invoices.vendor_name`, `invoices.total_cents`
- Genera: `SELECT vendor_name, SUM(total_cents) ... FROM invoices ... GROUP BY ... ORDER BY ... LIMIT 5`
- Responde con los 5 proveedores + montos

### ❌ Fuera del Dominio

**Pregunta:** "¿Qué tiempo hace?"
- Consulta schema → No encuentra nada sobre clima
- Responde: "Lo siento, solo puedo responder preguntas relacionadas con los datos de facturas en mi base de datos."

## Testing

### Ejecutar tests automáticos:

```bash
cd /home/simonll4/Desktop/ia/proyecto/pipeline-python
python tests/test_dynamic_system.py
```

### Tests manuales via API:

```bash
curl -X POST http://localhost:8000/api/v1/assistant/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-session",
    "question": "¿Cuál es el item más caro?"
  }'
```

## Verificaciones Importantes

### 1. ¿El fallback está desactivado?

```python
# En config.py debe estar:
DISABLE_FALLBACK = True
```

### 2. ¿El LLM consulta el schema?

```python
# En los logs deberías ver:
# "Tool call: get_database_schema"
```

### 3. ¿Rechaza preguntas fuera de dominio?

```python
# Test:
response = orchestrator.process_question("¿Qué es el COVID?")
# Esperado: needs_data=False y mensaje de limitación
```

## Variables de Entorno

```bash
# Obligatorias
GROQ_API_KEY=gsk_...
DB_PATH=/app/data/app.db

# Opcionales (ya con defaults correctos)
DISABLE_FALLBACK=1
MAX_HISTORY_MESSAGES=0
LLM_MODEL=llama-3.1-8b-instant
```

## Solución de Problemas

### ❌ "El sistema sigue usando respuestas hardcodeadas"

**Causa:** `DISABLE_FALLBACK` no está seteado o es `False`

**Solución:**
```bash
export DISABLE_FALLBACK=1
# o en .env:
DISABLE_FALLBACK=1
```

### ❌ "El LLM inventa nombres de columnas"

**Causa:** El prompt de RULE 0 no está siendo usado

**Solución:** Verificar que `_build_plan_system_prompt()` tiene el bloque:
```
═══════════════════════════════════════════════════════════════════════════════
RULE 0 — DOMAIN & SCHEMA:
...
```

### ❌ "Responde preguntas fuera de dominio"

**Causa:** El gate de dominio no está funcionando

**Solución:** Verificar que en `process_question()` existe:
```python
if not plan.get("needs_data") and not tool_runs:
    # ... mensaje de limitación
```

## Monitoring

### Logs a buscar:

```
✅ "Tool call: get_database_schema" → LLM consultó el schema
✅ "Tool call: execute_sql_query" → LLM generó SQL
✅ "Planner output attempt 1: {...}" → Ver el plan generado
❌ "Applying fallback plan" → El fallback NO debería aparecer si está desactivado
```

## Próximos Pasos

1. **Desplegar a producción** con `DISABLE_FALLBACK=1`
2. **Monitorear queries generadas** (agregar logging de SQLs)
3. **Ajustar prompts** si hay patrones de error
4. **Extender el schema** si se agregan más tablas

## Contacto

Para dudas o issues sobre la implementación, revisar:
- `/docs/DYNAMIC_SYSTEM_IMPLEMENTATION.md` (documentación completa)
- `/tests/test_dynamic_system.py` (suite de tests)

---

**Última actualización:** 2025-11-12  
**Autor:** Sistema de IA  
**Estado:** ✅ Production Ready
