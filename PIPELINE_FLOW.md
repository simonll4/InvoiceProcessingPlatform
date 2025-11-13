# 📄 Pipeline de Extracción de Facturas

## 🎯 Descripción General

El pipeline procesa documentos (PDFs o imágenes) para extraer información estructurada de facturas usando OCR, LLM (Groq) y validación regex.

---

## 🔄 Flujo Completo

### **Entrada**
- PDF (factura)
- Imagen (JPEG, PNG, etc.)

### **Salida**
- Datos estructurados en formato JSON
- Almacenamiento en SQLite (`data/app.db`)

---

## 📊 Diagrama de Flujo

```
┌─────────────────────────────────────────────────────────────────┐
│                         ENTRADA                                 │
│                    PDF o Imagen                                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. DETECCIÓN DE TIPO DE DOCUMENTO                             │
│     • detect_source(path)                                       │
│     • Retorna: "pdf" o "image"                                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                ┌───────────┴───────────┐
                │                       │
                ▼                       ▼
    ┌───────────────────┐   ┌───────────────────┐
    │   2a. PDF PATH    │   │  2b. IMAGE PATH   │
    └───────────────────┘   └───────────────────┘
                │                       │
                ▼                       ▼
    ┌───────────────────┐   ┌───────────────────┐
    │ extract_pdf_text()│   │extract_image_text()│
    │  • PyMuPDF        │   │  • Tesseract OCR  │
    │  • Max 5 páginas  │   │  • PIL (pillow)   │
    └───────────────────┘   └───────────────────┘
                │                       │
                └───────────┬───────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. TEXTO EXTRAÍDO (OCR)                                        │
│     • List[PageText] - Una o más páginas                        │
│     • Cada página contiene: lines, width, height, page_num      │
│                                                                 │
│     Ejemplo de texto extraído:                                  │
│     ┌─────────────────────────────────────────────────────┐   │
│     │ SuperStore                                          │   │
│     │ INVOICE # 5434                                      │   │
│     │ Bill To: Yana Sorensen                              │   │
│     │ Date: May 31 2012                                   │   │
│     │ Item          Quantity  Rate      Amount            │   │
│     │ Dania Library    2      $482.48   $964.96           │   │
│     │ Subtotal:                         $964.96           │   │
│     │ Shipping:                         $66.70            │   │
│     │ Total:                            $1,031.66         │   │
│     └─────────────────────────────────────────────────────┘   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. VALIDACIÓN DE CONTENIDO                                     │
│     • _ensure_pages(pages)                                      │
│     • Verifica que el texto no esté vacío                       │
│     • Min. caracteres: 50                                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. PREPARACIÓN DE TEXTO                                        │
│     • join_pages(pages)       → Texto unificado                 │
│     • _compact_prompt_text()  → Reduce newlines redundantes     │
│     • Preserva espaciado horizontal (importante para columnas)  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. CONSTRUCCIÓN DE PROMPT PARA LLM                             │
│     • build_messages(text)                                      │
│     • Mensaje de sistema: "Eres un experto en facturas..."     │
│     • Mensaje de usuario: Texto del documento                   │
│     • Esquema JSON requerido (invoice_v1)                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  7. LLAMADA AL LLM (GROQ)                                       │
│     • call_llm(messages, temperature=0.0)                       │
│     • Modelo: llama-3.1-8b-instant                              │
│     • Max tokens: dinámico (256 + 120 * páginas)                │
│     • Rate limiting automático (24 RPM, 4800 TPM)               │
│                                                                 │
│     ⚠️  NOTA: El LLM puede cometer errores en valores numéricos│
│                                                                 │
│     Ejemplo de respuesta del LLM:                               │
│     ┌─────────────────────────────────────────────────────┐   │
│     │ {                                                   │   │
│     │   "invoice": {                                      │   │
│     │     "invoice_number": "5434",                       │   │
│     │     "vendor_name": "SuperStore",                    │   │
│     │     "subtotal_cents": 103166,  ❌ PUEDE ESTAR MAL   │   │
│     │     "tax_cents": 6670,                              │   │
│     │     "discount_cents": 6670,    ❌ PUEDE ESTAR MAL   │   │
│     │     "total_cents": 103166                           │   │
│     │   },                                                │   │
│     │   "items": [...]                                    │   │
│     │ }                                                   │   │
│     └─────────────────────────────────────────────────────┘   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  8. VALIDACIÓN Y PARSING DE RESPUESTA                           │
│     • parse_response(raw_json)                                  │
│     • Valida contra esquema Pydantic (InvoiceV1)                │
│     • Lanza InvalidLLMResponse si el JSON es inválido           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  9. EXTRACCIÓN MANUAL DE VALORES (OVERRIDE) ⭐                  │
│     • _extract_summary_values(document_text)                    │
│     • Usa REGEX sobre el texto original (no el LLM)             │
│     • Patrones:                                                 │
│       - SUMMARY_LABEL_PATTERN: Subtotal, Discount, Tax, etc.   │
│       - AMOUNT_PATTERN: $XXX.XX                                 │
│                                                                 │
│     Algoritmo:                                                  │
│     ┌─────────────────────────────────────────────────────┐   │
│     │ 1. Encontrar todos los labels (Subtotal, Discount) │   │
│     │ 2. Encontrar todos los amounts ($964.96, $66.70)   │   │
│     │ 3. Filtrar porcentajes (20% en "Discount (20%)")   │   │
│     │ 4. Detectar grupos de labels consecutivos          │   │
│     │    • Sin amounts entre ellos → GRUPO               │   │
│     │    • Con amounts cerca → STANDALONE                │   │
│     │ 5. Para GRUPOS: matchear en orden                  │   │
│     │    Label1 → Amount1, Label2 → Amount2, etc.        │   │
│     │ 6. Para STANDALONE: matchear amount más cercano    │   │
│     └─────────────────────────────────────────────────────┘   │
│                                                                 │
│     Ejemplo de extracción:                                      │
│     Input:  "Subtotal:\n Shipping:\n $964.96\n $66.70"         │
│     Output: {'subtotal': 96496, 'addition': 6670}              │
│                                                                 │
│     ✅ ESTO CORRIGE LOS ERRORES DEL LLM                         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  10. APLICACIÓN DE OVERRIDES                                    │
│      • _apply_summary_overrides(invoice, summary_values)        │
│      • Si summary_values tiene 'subtotal', reemplaza el del LLM│
│      • Si summary_values tiene 'discount', reemplaza el del LLM│
│      • Si summary_values tiene 'total', reemplaza el del LLM   │
│      • Retorna set de campos sobrescritos                       │
│                                                                 │
│      Antes:  invoice.subtotal_cents = 103166 (del LLM ❌)      │
│      Después: invoice.subtotal_cents = 96496 (del regex ✅)     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  11. NORMALIZACIÓN DE MONTOS                                    │
│      • _normalize_invoice_amounts(invoice)                      │
│      • Infiere valores faltantes usando fórmulas:               │
│        - total = subtotal + tax - discount                      │
│        - subtotal = total - tax + discount                      │
│        - tax = total - subtotal + discount                      │
│      • Clampea valores negativos a 0                            │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  12. CLASIFICACIÓN Y NORMALIZACIÓN DE ITEMS                     │
│      • classify_item(description, vendor_name)                  │
│      • Asigna categorías: Electronics, Office, Furniture, etc.  │
│      • LLM categoriza cada item basado en la descripción        │
│      • Default qty = 1.0 si falta                               │
│      • Merge de items descriptivos (sin precio)                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  13. RECÁLCULO DE DESCUENTO                                     │
│      • _recompute_discount(invoice, discount_locked)            │
│      • Solo recalcula si discount NO fue extraído manualmente   │
│      • Fórmula: discount = subtotal + tax - total               │
│      • Si discount_locked=True → NO recalcula (usa el override) │
│                                                                 │
│      Ejemplo:                                                   │
│      • subtotal=96496, tax=6670, total=103166                   │
│      • expected = 96496 + 6670 - 103166 = 0                     │
│      • discount = 0 ✅                                           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  14. VALIDACIÓN DE CONSISTENCIA                                 │
│      • Suma de line items vs subtotal/total                     │
│      • Tolerancia: 1% del valor esperado                        │
│      • Genera warnings si hay discrepancias                     │
│      • Escala automática si todos los valores están 100x off    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  15. CONVERSIÓN A DICT Y GUARDADO                               │
│      • model.model_dump(mode="json")                            │
│      • save_document(path, file_hash, raw_text, payload)        │
│      • SQLite: data/app.db                                      │
│      • Caché por file_hash (evita reprocesar mismo archivo)     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         SALIDA                                  │
│                                                                 │
│  {                                                              │
│    "schema_version": "invoice_v1",                              │
│    "invoice": {                                                 │
│      "invoice_number": "5434",                                  │
│      "invoice_date": "2012-05-31",                              │
│      "vendor_name": "SuperStore",                               │
│      "buyer_name": "Yana Sorensen",                             │
│      "currency_code": "USD",                                    │
│      "subtotal_cents": 96496,     ✅ CORREGIDO                  │
│      "tax_cents": 6670,                                         │
│      "discount_cents": 0,          ✅ CORREGIDO                 │
│      "total_cents": 103166                                      │
│    },                                                           │
│    "items": [                                                   │
│      {                                                          │
│        "idx": 1,                                                │
│        "description": "Dania Library with Doors, Metal",        │
│        "qty": 2.0,                                              │
│        "unit_price_cents": 48248,                               │
│        "line_total_cents": 96496,                               │
│        "category": "Furniture"                                  │
│      }                                                          │
│    ],                                                           │
│    "notes": {                                                   │
│      "warnings": null,                                          │
│      "confidence": 1.0                                          │
│    }                                                            │
│  }                                                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔍 Diferencias: PDF vs Imagen

### **PDF (extract_pdf_text)**
```python
# Librería: PyMuPDF (fitz)
# Características:
• Extracción nativa de texto (si el PDF tiene texto embebido)
• Fallback a OCR si es PDF escaneado
• Soporte multi-página (max 5 páginas por defecto)
• Preserva estructura de columnas y espaciado
• Más rápido que OCR de imágenes

# Código:
doc = fitz.open(path)
for page in doc:
    text = page.get_text("text")
    # O fallback a OCR con page.get_pixmap()
```

### **Imagen (extract_image_text)**
```python
# Librería: Tesseract OCR + PIL
# Características:
• OCR completo (siempre)
• Soporta JPEG, PNG, TIFF, BMP, etc.
• Una sola "página"
• Más lento que PDF nativo
• Puede tener más errores de OCR

# Código:
image = Image.open(path)
text = pytesseract.image_to_string(image, lang='eng')
```

### **Comparación**

| Característica       | PDF                          | Imagen                    |
|---------------------|------------------------------|---------------------------|
| **Velocidad**       | Rápido (texto nativo)        | Lento (siempre OCR)       |
| **Precisión**       | Alta (si tiene texto)        | Depende de calidad        |
| **Multi-página**    | ✅ Sí (max 5)                | ❌ No                     |
| **Formato entrada** | .pdf                         | .jpg, .png, .tiff, etc.   |
| **Librería**        | PyMuPDF (fitz)               | Tesseract + PIL           |

---

## ⚙️ Configuración

### **Variables de Entorno** (`configs/env/.env`)
```bash
# LLM
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.1-8b-instant

# OCR
PDF_OCR_DPI=300
PDF_OCR_MAX_PAGES=5
TEXT_MIN_LENGTH=50

# Pipeline
DEFAULT_CURRENCY=USD
MAX_CONCURRENCY=1

# Rate Limits (Groq)
RATE_LIMIT_RPM=24
RATE_LIMIT_TPM=4800
```

### **Archivos Clave**
```
src/modules/pipeline/
├── service/
│   └── pipeline.py          # Orquestación principal
├── extract/
│   └── text_extractor.py    # OCR (PDF/imagen)
├── llm/
│   ├── groq_client.py       # Cliente Groq
│   ├── prompts.py           # Construcción de prompts
│   └── validator.py         # Validación de respuestas
├── storage/
│   └── db.py                # Persistencia SQLite
└── schema/
    └── invoice_v1.py        # Modelos Pydantic
```

---

## 🎯 Casos de Uso Exitosos

### **Caso 1: Factura sin descuento**
```
Input:  invoice_Yana Sorensen_5434.pdf
        Subtotal: $964.96
        Shipping: $66.70
        Total: $1,031.66

Output: ✅
        subtotal_cents: 96496
        tax_cents: 6670
        discount_cents: 0
        total_cents: 103166
```

### **Caso 2: Factura con descuento 20%**
```
Input:  invoice_Allen Rosenblatt_33571.pdf
        Subtotal: $143.43
        Discount (20%): $28.69
        Shipping: $14.91
        Total: $129.65

Output: ✅
        subtotal_cents: 14343
        tax_cents: 1491
        discount_cents: 2869
        total_cents: 12965
```

---

## 🐛 Resolución de Problemas

### **Problema**: El LLM extrae valores incorrectos
**Solución**: `_extract_summary_values()` corrige automáticamente usando regex sobre el texto original.

### **Problema**: OCR no extrae texto
**Solución**: 
- Verifica calidad de imagen (min 300 DPI)
- Asegúrate de que Tesseract esté instalado
- Revisa logs: `TEXT_MIN_LENGTH=50` caracteres mínimos

### **Problema**: Rate limit excedido
**Solución**: Ajusta `RATE_LIMIT_RPM` y `RATE_LIMIT_TPM` en `.env`

---

## 📊 Base de Datos

### **Esquema SQLite** (`data/app.db`)
```sql
CREATE TABLE invoices (
    id INTEGER PRIMARY KEY,
    path VARCHAR NOT NULL,
    file_hash VARCHAR UNIQUE,
    raw_text TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    invoice_number VARCHAR,
    invoice_date VARCHAR NOT NULL,
    vendor_name VARCHAR NOT NULL,
    buyer_name VARCHAR,
    subtotal_cents INTEGER,
    tax_cents INTEGER,
    discount_cents INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    confidence FLOAT,
    warnings TEXT
);

CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER,
    idx INTEGER,
    description TEXT,
    qty FLOAT,
    unit_price_cents INTEGER,
    line_total_cents INTEGER,
    category VARCHAR,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id)
);
```

### **Consulta de ejemplo**
```sql
SELECT 
    invoice_number,
    vendor_name,
    subtotal_cents/100.0 as subtotal,
    discount_cents/100.0 as discount,
    total_cents/100.0 as total
FROM invoices
ORDER BY id;
```

---

## 🚀 Ejecución

### **Via API** (recomendado)
```bash
# Subir factura
curl -X POST http://localhost:7000/api/pipeline/extract \
  -F "file=@invoice.pdf"

# Consultar resultados
curl http://localhost:7000/api/monitoring/invoices
```

### **Via Python directo**
```python
from src.modules.pipeline.service.pipeline import run_pipeline

result = run_pipeline("/path/to/invoice.pdf")
print(result["invoice"]["subtotal_cents"])
```

---

## 📝 Notas Técnicas

1. **Cache por file_hash**: Si subes el mismo PDF dos veces, el resultado se obtiene de caché instantáneamente.

2. **Escala automática**: Si todos los montos están 100x off (ej: LLM devuelve centavos en lugar de dólares), el sistema lo detecta y corrige.

3. **Warnings inteligentes**: Filtra falsos positivos como "Line item sum doesn't match" cuando la diferencia es por redondeo.

4. **Rate limiting**: Implementado para Groq (24 RPM, 4800 TPM) con reintentos automáticos.

5. **Regex resiliente**: Maneja múltiples formatos:
   - Labels en una línea, amounts en otra
   - Todo en una línea separado por espacios
   - Porcentajes en labels de descuento (`Discount (20%)`)
