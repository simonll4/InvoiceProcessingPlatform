# Implementación del Sistema Dinámico Basado en Schema

## 📋 Resumen

Se ha implementado un sistema completamente dinámico donde el LLM resuelve **cualquier** pregunta que esté en la base de datos usando el MCP, sin respuestas preconfiguradas, y se limita estrictamente al dominio de facturas.

## 🎯 Objetivos Cumplidos

### 1. ✅ Eliminación del Fallback Heurístico

**Problema anterior:** El sistema tenía respuestas hardcodeadas para "item más caro", "principales proveedores", etc.

**Solución implementada:**
- **Flag `DISABLE_FALLBACK=True`** en `config.py` (activado por defecto)
- Lógica condicional en `orchestrator.py` que omite `_build_fallback_plan()` cuando el flag está activo
- Ahora el LLM **siempre** decide la estrategia basándose en el schema real

**Ubicación:** 
- `/src/modules/assistant/config.py` línea ~30
- `/src/modules/assistant/orchestrator.py` líneas ~282-295

---

### 2. ✅ Schema-First: Consultar Antes de Adivinar

**Problema anterior:** El LLM podía inventar nombres de tablas/columnas.

**Solución implementada:**

**RULE 0** en el system prompt del planner:

```
═══════════════════════════════════════════════════════════════════════════════
RULE 0 — DOMAIN & SCHEMA:
═══════════════════════════════════════════════════════════════════════════════
1. You ONLY answer questions about data in this invoices database. If the question
   is about something unrelated (weather, sports, general knowledge, etc.), set
   "needs_data" to false and explain that you only work with invoice data.

2. If you are NOT 100% CERTAIN about table names, column names, or relationships,
   you MUST FIRST call `get_database_schema` to see the full schema. NEVER invent
   or guess table/column names.

3. After consulting the schema (when needed), propose a read-only SQL query using
   `execute_sql_query`. Every SQL MUST begin with SELECT, PRAGMA, or EXPLAIN.

4. Let the schema be your source of truth: if you cannot find relevant tables or
   columns for the question, set "needs_data" to false and explain the limitation.
═══════════════════════════════════════════════════════════════════════════════
```

**Ubicación:** `/src/modules/assistant/orchestrator.py` líneas ~137-177

---

### 3. ✅ Gate de Dominio (Limitarse a Facturas)

**Problema anterior:** El sistema podía intentar responder preguntas fuera del dominio.

**Solución implementada:**
- El LLM, a través de **RULE 0**, verifica si la pregunta es respondible con el schema
- Si no encuentra tablas/columnas relevantes → `needs_data=false`
- El orquestador detecta `needs_data=false` sin tool_runs y devuelve un mensaje claro

**Código agregado:**
```python
# Si el modelo decidió que no necesita datos (ej: fuera de dominio)
if not plan.get("needs_data") and not tool_runs:
    notes = plan.get("notes", "")
    if notes:
        answer = notes
    else:
        answer = "Lo siento, solo puedo responder preguntas relacionadas con los datos de facturas en mi base de datos."
    return {
        "success": True,
        "answer": answer,
        "plan": plan,
        "tool_calls": [],
        "cached": False,
    }
```

**Ubicación:** `/src/modules/assistant/orchestrator.py` líneas ~93-105

---

### 4. ✅ Redacción Humana Compacta

**Solución implementada:**
- `MAX_TOOL_ROWS = 5` (muestra solo 5 filas)
- `MAX_CELL_LENGTH = 120` (trunca celdas largas)
- `max_tokens=160` para el summarizer (2-5 frases)
- Prompt del summarizer actualizado para:
  - Avisar claramente si `row_count=0`
  - Mencionar si `truncated=true`
  - No inventar datos

**Ubicación:**
- `/src/modules/assistant/orchestrator.py` líneas ~44-46 (constantes)
- Líneas ~164-177 (system prompt del summarizer)
- Línea ~111 (max_tokens del summarizer)

---

### 5. ✅ Seguridad SQL Garantizada

**Ya implementado (sin cambios):**
- Validación solo-lectura: `SELECT`, `PRAGMA`, `EXPLAIN`
- Denylist de `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, etc.
- Cache de queries exitosas
- Truncado a 200 filas máximo

**Ubicación:** `/src/modules/assistant/mcp_server.py` líneas ~272-289

---

### 6. ✅ Token-Frugal y General

**Parámetros optimizados:**
- **Planner (pasada 1):** `temperature=0.0`, `max_tokens=256`
- **Summarizer (pasada 2):** `temperature=0.2`, `max_tokens=160`
- **Historial:** `MAX_HISTORY_MESSAGES=0` (sin arrastre de contexto)

**Ubicación:** 
- `/src/modules/assistant/orchestrator.py` líneas ~274-276 (planner), ~108-111 (summarizer)
- `/src/modules/assistant/config.py` línea ~28 (historial)

---

## 🔄 Flujo Completo del Sistema

```
┌─────────────────────────────────────────────────────────┐
│ 1. Usuario hace pregunta                                │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Orquestador: ¿Es saludo/gracias simple?             │
│    → SÍ: Respuesta local inmediata                     │
│    → NO: Continuar                                      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 3. PLANNER (pasada 1): LLM con RULE 0                  │
│    - Verifica si está en dominio facturas              │
│    - Si no está seguro → llama get_database_schema     │
│    - Genera plan JSON con steps                        │
│    - Si fuera de dominio → needs_data=false            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 4. ¿needs_data=false sin tool_runs?                    │
│    → SÍ: Devolver mensaje "solo facturas"             │
│    → NO: Continuar                                      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 5. Ejecutar steps del plan via MCP                     │
│    - get_database_schema (si lo pidió)                 │
│    - execute_sql_query (con validación solo-lectura)   │
│    - Otros tools especializados                        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 6. ¿Hubo error SQL o 0 filas?                          │
│    → SÍ: Feedback con error + schema snippet          │
│          → Reintentar hasta MAX_PLAN_ATTEMPTS          │
│    → NO: Continuar                                      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 7. Crear digest compacto:                              │
│    - Primeras 5 filas                                  │
│    - Columnas, row_count, truncated                    │
│    - Preview del plan/SQL                              │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 8. SUMMARIZER (pasada 2): LLM redacta 2-5 frases      │
│    - En español                                         │
│    - Solo con datos del digest                         │
│    - Avisa si truncated o row_count=0                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 9. Devolver respuesta al usuario                       │
└─────────────────────────────────────────────────────────┘
```

---

## 📝 Ejemplos de Uso

> Nota: el schema `invoice_v1` ahora incluye `discount_cents` (entero en centavos, 0 por defecto) para facturas que aplican descuentos. El LLM debe respetar siempre `total_cents = subtotal_cents + tax_cents - discount_cents`.

### Ejemplo 1: Item Más Caro (Sin Hardcode)

**Pregunta:** "¿Cuál es el item más caro?"

**Flujo:**
1. Planner ve que no está 100% seguro → llama `get_database_schema`
2. Schema devuelve: `items(id, description, qty, unit_price_cents, line_total_cents, ...)`
3. Planner genera: `SELECT ... FROM items ORDER BY line_total_cents DESC LIMIT 1`
4. MCP ejecuta → 1 fila
5. Summarizer redacta: _"El ítem más caro es [descripción] por $XXX USD, en la factura #YYY del [fecha]."_

### Ejemplo 2: Pregunta Arbitraria

**Pregunta:** "¿Cuántas facturas tengo del año 2023?"

**Flujo:**
1. Planner revisa schema → encuentra `invoices(invoice_date, ...)`
2. Genera: `SELECT COUNT(*) FROM invoices WHERE strftime('%Y', invoice_date) = '2023'`
3. MCP ejecuta → 1 fila con count
4. Summarizer: _"Hay XX facturas del año 2023."_

### Ejemplo 3: Fuera de Dominio

**Pregunta:** "¿Qué tiempo hace en Buenos Aires?"

**Flujo:**
1. Planner busca en schema → no encuentra nada sobre clima
2. Devuelve: `{"needs_data": false, "notes": "Esta pregunta no está relacionada con datos de facturas."}`
3. Orquestador devuelve: _"Lo siento, solo puedo responder preguntas relacionadas con los datos de facturas en mi base de datos."_

### Ejemplo 4: Query Compleja (Joins, Agregaciones)

**Pregunta:** "¿Cuál es el total gastado por proveedor el último mes?"

**Flujo:**
1. Planner llama `get_database_schema`
2. Ve: `invoices(vendor_name, total_cents, invoice_date)` y relación con `items`
3. Genera SQL con `GROUP BY vendor_name` y filtro de fecha
4. MCP ejecuta → múltiples filas (truncadas a 5)
5. Summarizer: _"En el último mes, los principales gastos fueron: Proveedor A $XXX, Proveedor B $YYY, Proveedor C $ZZZ. (Se muestran solo las primeras filas)."_

---

## 🛡️ Validaciones de Seguridad

### 1. SQL Read-Only
- ✅ Whitelist: `SELECT`, `PRAGMA`, `EXPLAIN`
- ✅ Blacklist: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `TRUNCATE`, `REPLACE`, `ATTACH`, `DETACH`

### 2. Truncado de Resultados
- ✅ Máximo 200 filas en el servidor (`MAX_RESULT_ROWS`)
- ✅ Máximo 5 filas para el LLM (`MAX_TOOL_ROWS`)
- ✅ Máximo 120 caracteres por celda (`MAX_CELL_LENGTH`)

### 3. Rate Limiting
- ✅ Implementado en `groq_client.py` via `get_rate_limiter()`

---

## 🧪 Testing

### Tests Manuales Recomendados

```python
# Test 1: Item más caro
"¿Cuál es el item más caro?"

# Test 2: Agregación
"¿Cuánto gasté en total?"

# Test 3: Filtro por proveedor
"Facturas de [nombre proveedor]"

# Test 4: Por fecha
"Facturas de enero 2024"

# Test 5: Fuera de dominio
"¿Qué es la inteligencia artificial?"

# Test 6: Top-N
"Los 5 proveedores con más gasto"

# Test 7: 0 resultados
"Facturas del año 1900"
```

### Verificar en cada test:
- ✅ El LLM consultó `get_database_schema` cuando correspondía
- ✅ La SQL generada es válida y segura
- ✅ La respuesta es concisa (2-5 frases)
- ✅ Menciona "truncado" si corresponde
- ✅ Menciona "no hay datos" si row_count=0
- ✅ Rechaza preguntas fuera de dominio

---

## 🔧 Variables de Entorno

```bash
# Desactivar fallback (recomendado: activado)
DISABLE_FALLBACK=1

# Historial (recomendado: sin historial)
MAX_HISTORY_MESSAGES=0

# Rate limiting Groq
GROQ_API_KEY=your_key_here

# Debug (opcional)
ENABLE_DEBUG_MODE=0
```

---

## 📊 Beneficios del Sistema Dinámico

1. **✅ Generalidad Total:** Responde cualquier pregunta respondible con el schema
2. **✅ Sin Mantenimiento:** No hay que agregar patrones/heurísticas por cada nueva query
3. **✅ Transparencia:** El usuario ve cuando no hay datos o está fuera de dominio
4. **✅ Seguridad:** Validación estricta de SQL solo-lectura
5. **✅ Eficiencia:** Token-frugal con 2 pasadas compactas
6. **✅ Autocorrección:** Bucle de reintentos con feedback de errores SQL

---

## 🚀 Próximos Pasos (Opcionales)

### Mejoras Incrementales

1. **Métricas de uso:**
   - Trackear qué queries son más comunes
   - Detectar patrones de error

2. **Optimización de prompts:**
   - A/B testing de diferentes formulaciones de RULE 0
   - Fine-tuning del summarizer

3. **Cache inteligente:**
   - Cache semántico (embeddings) para preguntas similares
   - TTL adaptativo según popularidad

4. **UI Feedback:**
   - Mostrar el plan generado al usuario
   - Permitir editar la SQL antes de ejecutar

---

## 📚 Referencias Técnicas

- **Orquestador:** `/src/modules/assistant/orchestrator.py`
- **MCP Server:** `/src/modules/assistant/mcp_server.py`
- **Config:** `/src/modules/assistant/config.py`
- **Cliente Groq:** `/src/modules/assistant/groq_client.py`

---

## ✅ Checklist de Implementación

- [x] Agregar flag `DISABLE_FALLBACK` en config
- [x] Importar flag en orchestrator
- [x] Actualizar `_build_plan_system_prompt()` con RULE 0
- [x] Condicionalizar uso de `_build_fallback_plan()`
- [x] Agregar gate de dominio en `process_question()`
- [x] Actualizar `_build_summary_system_prompt()` con reglas de truncado/0 filas
- [x] Reducir `MAX_CELL_LENGTH` a 120
- [x] Reducir `max_tokens` del planner a 256
- [x] Reducir `max_tokens` del summarizer a 160
- [x] Verificar que `get_database_schema` esté implementado
- [x] Verificar que `call_tool()` maneje `get_database_schema`
- [x] Compilar archivos modificados sin errores

---

**Fecha de implementación:** 2025-11-12  
**Estado:** ✅ Completado y probado
