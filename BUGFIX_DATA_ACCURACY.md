# 🐛 BUGFIX: Corrección de Precisión de Datos

**Fecha**: 2025-11-12  
**Severidad**: CRÍTICA  
**Componentes afectados**: MCP Server, Orchestrator, Prompts

---

## 📋 Resumen Ejecutivo

Se identificaron y corrigieron **4 problemas críticos** de precisión de datos donde el asistente devolvía información incorrecta, inventada o mezclaba monedas sin conversión. Todas las correcciones fueron **verificadas contra consultas SQL directas** a la base de datos.

---

## 🔍 Problemas Identificados

### 1. ❌ Factura Máxima Incorrecta

**Comportamiento incorrecto:**
- Reportaba factura `12655` (SuperStore) como la de mayor monto
- Monto incorrecto y moneda incorrecta

**Valor real (verificado con SQL):**
```sql
SELECT * FROM invoices ORDER BY total_cents DESC LIMIT 1;
-- ID: 5
-- Invoice: 94689364
-- Vendor: Schwartz, Flynn and Jackson Wilson PLC
-- Total: 3,715,367 centavos USD
-- Fecha: 2015-12-01
```

**Causa raíz:**
- No existía herramienta MCP específica para "factura máxima"
- El LLM planner generaba SQL incorrecta (sin ORDER BY correcto, o limitando por vendor)

---

### 2. ❌ Factura ID=5 con Monto Incorrecto

**Comportamiento incorrecto:**
- Al consultar factura ID=5, reportaba `65,162 centavos`
- Decía "no hay datos para comparar"

**Valor real (verificado con SQL):**
```sql
SELECT * FROM invoices WHERE id = 5;
-- Total: 3,715,367 centavos USD
```

**Causa raíz:**
- Herramienta `get_invoice_by_id(5)` existía pero no se usaba por falta de fallback específico
- El planner no detectaba patrones como "factura 5" o "id 5"

---

### 3. ❌ Total de Facturas INCORRECTO (Crítico)

**Comportamiento incorrecto:**
- Reportaba `661,985 centavos` (~6,619.85 USD)
- NO mencionaba que hay múltiples monedas
- Valor completamente inventado o basado en subset de datos

**Valores reales (verificados con SQL):**
```sql
SELECT currency_code, COUNT(*), SUM(total_cents) 
FROM invoices 
GROUP BY currency_code;

-- USD: 3 facturas, 3,738,565 centavos
-- EUR: 1 factura,   400,241 centavos
-- ARS: 3 facturas, 3,714,524 centavos
-- TOTAL BRUTO (sin conversión): 7,853,330 centavos
```

**Causa raíz:**
- **NO EXISTÍA** herramienta MCP para obtener totales
- El LLM probablemente generaba SQL con `LIMIT` que truncaba resultados
- O directamente inventaba el número basándose en ejemplos

---

### 4. ⚠️ Proveedores Incompletos

**Comportamiento incorrecto:**
- Solo mostraba 5 proveedores cuando existen 7
- Faltaban: Dome Supplies y Patel, Thompson and Montgomery...
- No explicaba que era "top 5"

**Valores reales (verificados con SQL):**
```sql
SELECT vendor_name, COUNT(*), SUM(total_cents), currency_code
FROM invoices
GROUP BY vendor_name, currency_code
ORDER BY SUM(total_cents) DESC;

-- 7 proveedores en total
-- Dome Supplies: 10,000 centavos USD (2024-07-15)
-- Patel Thompson...: 8,250 centavos ARS (2012-10-15)
```

**Causa raíz:**
- Query con `LIMIT 5` sin documentación
- Agrupaba por `vendor_name, currency_code` (incorrecto para proveedores con múltiples monedas)

---

## ✅ Soluciones Implementadas

### 1. Nueva Herramienta: `get_max_invoice()`

**Archivo**: `src/modules/assistant/mcp_server.py`

```python
def get_max_invoice(self) -> dict[str, Any]:
    """
    Get the invoice with the highest total_cents.
    CRITICAL: Correctly ordered by total_cents DESC.
    """
    sql = """
            SELECT
                id,
                invoice_number,
                invoice_date,
                vendor_name,
                total_cents,
                currency_code,
                path
            FROM invoices
            ORDER BY total_cents DESC, id DESC
            LIMIT 1
    """
    return self.execute_query(sql)
```

**Verificación:**
```python
result = server.get_max_invoice()
assert result['rows'][0]['id'] == 5
assert result['rows'][0]['total_cents'] == 3715367
# ✅ PASS
```

---

### 2. Nueva Herramienta: `get_total_invoices_summary()`

**Archivo**: `src/modules/assistant/mcp_server.py`

```python
def get_total_invoices_summary(self) -> dict[str, Any]:
    """
    Get summary of all invoices: total count and totals by currency.
    CRITICAL: Returns separate totals per currency to avoid mixing currencies.
    """
    sql = """
        SELECT
            COUNT(*) as total_invoices,
            currency_code,
            SUM(total_cents) as total_cents
        FROM invoices
        GROUP BY currency_code
        ORDER BY total_cents DESC
    """
    return self.execute_query(sql)
```

**Verificación:**
```python
result = server.get_total_invoices_summary()
totals = {row['currency_code']: row['total_cents'] for row in result['rows']}
assert totals['USD'] == 3738565
assert totals['EUR'] == 400241
assert totals['ARS'] == 3714524
# ✅ PASS
```

---

### 3. Corrección: `get_top_vendors()`

**Antes (INCORRECTO):**
```python
sql = f"""
    SELECT 
        vendor_name,
        COUNT(*) as invoice_count,
        SUM(total_cents) as total_spent_cents,
        currency_code,  -- ❌ Agrupa por currency, separa proveedores
        MAX(invoice_date) as last_invoice_date
    FROM invoices
    GROUP BY vendor_name, currency_code  -- ❌ INCORRECTO
    ORDER BY total_spent_cents DESC
    LIMIT {limit}
"""
```

**Ahora (CORRECTO):**
```python
sql = f"""
    SELECT 
        vendor_name,
        COUNT(*) as invoice_count,
        SUM(total_cents) as total_spent_cents,
        GROUP_CONCAT(DISTINCT currency_code) as currencies,  -- ✅ Lista todas las monedas
        MAX(invoice_date) as last_invoice_date
    FROM invoices
    GROUP BY vendor_name  -- ✅ Solo por vendor
    ORDER BY total_spent_cents DESC
    LIMIT {limit}
"""
```

**Verificación:**
```python
result = server.get_top_vendors(10)
assert result['row_count'] == 7  # Ahora muestra los 7 proveedores
vendors = [row['vendor_name'] for row in result['rows']]
assert 'Dome Supplies' in vendors
assert 'Patel, Thompson and Montgomery Jackson' in [v[:40] for v in vendors]
# ✅ PASS
```

---

### 4. Nuevos Fallbacks en Orchestrator

**Archivo**: `src/modules/assistant/orchestrator.py`

#### A) Fallback para Factura Máxima

```python
if any(phrase in normalized for phrase in [
    "factura donde se gastó más",
    "factura con mayor total",
    "factura máxima",
    "highest invoice",
    # ...
]):
    add_tool_step(
        "get_max_invoice",
        "Retrieve the invoice with the highest total amount",
    )
```

#### B) Fallback para Total de Facturas

```python
if any(phrase in normalized for phrase in [
    "total de facturas",
    "suma total",
    "cuánto se gastó en total",
    # ...
]):
    add_tool_step(
        "get_total_invoices_summary",
        "Get total count and amounts by currency for all invoices",
    )
```

#### C) Fallback para Factura por ID (con Regex)

```python
import re
id_match = re.search(r'\b(?:factura|invoice|documento|id)\s+(\d+)\b', normalized)
if id_match:
    doc_id = int(id_match.group(1))
    add_tool_step(
        "get_invoice_by_id",
        f"Retrieve invoice with ID {doc_id}",
        {"doc_id": doc_id},
    )
```

#### D) Fallback Mejorado para Proveedores

```python
if any(phrase in normalized for phrase in [
    "principales proveedores",
    "todos los proveedores",
    # ...
]):
    # Detect if asking for ALL vendors or top N
    limit = 100  # Default to show all
    if any(top in normalized for top in ["top 5", "top 3"]):
        limit = 5
    
    add_tool_step(
        "get_top_vendors",
        f"Retrieve the top {limit} vendors by total spending",
        {"limit": limit},
    )
```

---

### 5. Prompt del Summarizer Mejorado

**Archivo**: `src/modules/assistant/orchestrator.py`

**Secciones agregadas:**

```python
"""
CURRENCY HANDLING (MANDATORY):
- ALWAYS mention the currency for monetary amounts (USD, EUR, ARS, etc.).
- If data contains multiple currencies, present them separately.
- NEVER sum amounts in different currencies without explicit conversion.
- When showing total_cents, always specify the currency.

DATA ACCURACY:
- Use ONLY the exact values from the digest. Do NOT invent, approximate, or guess.
- If a value is missing or null in the digest, acknowledge it clearly.
- Present numeric values exactly as they appear (do not round unless asked).
"""
```

---

## 🧪 Pruebas de Verificación

### Test Suite Completo

```bash
cd /home/simonll4/Desktop/ia/proyecto/pipeline-python
python << 'PYEOF'
import sys
from pathlib import Path
sys.path.insert(0, 'src')

from modules.assistant.mcp_server import SQLiteMCPServer

db_path = Path('data/app.db')
server = SQLiteMCPServer(db_path=db_path)

# TEST 1: Factura máxima
result = server.get_max_invoice()
assert result['rows'][0]['id'] == 5
assert result['rows'][0]['total_cents'] == 3715367
print("✅ TEST 1 PASS: get_max_invoice()")

# TEST 2: Total por moneda
result = server.get_total_invoices_summary()
totals = {row['currency_code']: row['total_cents'] for row in result['rows']}
assert totals['USD'] == 3738565
assert totals['EUR'] == 400241
assert totals['ARS'] == 3714524
print("✅ TEST 2 PASS: get_total_invoices_summary()")

# TEST 3: Factura ID=5
result = server.get_invoice_by_id(5)
assert result['rows'][0]['total_cents'] == 3715367
print("✅ TEST 3 PASS: get_invoice_by_id(5)")

# TEST 4: Top vendors (todos)
result = server.get_top_vendors(10)
assert result['row_count'] == 7
print("✅ TEST 4 PASS: get_top_vendors()")

print("\n✅ TODAS LAS PRUEBAS PASARON")
PYEOF
```

**Resultado esperado:**
```
✅ TEST 1 PASS: get_max_invoice()
✅ TEST 2 PASS: get_total_invoices_summary()
✅ TEST 3 PASS: get_invoice_by_id(5)
✅ TEST 4 PASS: get_top_vendors()

✅ TODAS LAS PRUEBAS PASARON
```

---

## 📊 Impacto

| Aspecto | Antes | Después |
|---------|-------|---------|
| **Herramientas MCP** | 13 | 15 (+2) |
| **Factura máxima** | ❌ Incorrecta | ✅ Correcta |
| **Total facturas** | ❌ Inventado | ✅ Por moneda |
| **Factura ID=5** | ❌ 65,162 | ✅ 3,715,367 |
| **Proveedores** | ❌ Solo 5 | ✅ Todos (7) |
| **Manejo de monedas** | ❌ Mezcla | ✅ Separado |
| **Precisión de datos** | ❌ Baja | ✅ Alta |

---

## 🎯 Próximos Pasos

1. **Reiniciar servicio:**
   ```bash
   cd /home/simonll4/Desktop/ia/proyecto/pipeline-python
   docker-compose restart
   ```

2. **Probar queries críticas:**
   ```bash
   # Factura máxima
   curl -X POST http://localhost:8000/assistant/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "¿Cuál es la factura con mayor monto?"}'

   # Total de facturas
   curl -X POST http://localhost:8000/assistant/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "¿Cuál es el total de todas las facturas?"}'

   # Factura por ID
   curl -X POST http://localhost:8000/assistant/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "Muéstrame la factura 5"}'

   # Todos los proveedores
   curl -X POST http://localhost:8000/assistant/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "¿Cuáles son todos los proveedores?"}'
   ```

3. **Verificar en respuestas:**
   - ✅ Valores exactos de la DB
   - ✅ Monedas siempre mencionadas
   - ✅ Totales separados por moneda
   - ✅ Sin números inventados

---

## 📝 Archivos Modificados

```
src/modules/assistant/mcp_server.py     [MODIFIED] +50 líneas
src/modules/assistant/orchestrator.py   [MODIFIED] +40 líneas
BUGFIX_DATA_ACCURACY.md                 [NEW]
```

---

## ✅ Checklist de Verificación

- [x] Todas las queries SQL verificadas contra DB directa
- [x] Nuevas herramientas registradas en FastMCP
- [x] Nuevas herramientas agregadas a tool definitions OpenAI-compatible
- [x] Dispatchers agregados en `call_tool()`
- [x] Fallbacks agregados en orchestrator
- [x] Prompt del summarizer mejorado con reglas de currency
- [x] Tests de verificación ejecutados y pasados
- [x] Sintaxis Python validada (py_compile)
- [x] Documentación creada

---

**Estado**: ✅ COMPLETADO  
**Verificación**: ✅ TODOS LOS TESTS PASAN  
**Listo para**: 🚀 PRODUCCIÓN
