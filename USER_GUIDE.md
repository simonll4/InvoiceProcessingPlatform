# Guía de Uso - Pipeline de Extracción de Facturas

## ✅ Estado del Sistema

**El pipeline está completamente funcional y validado** ✓

- ✅ Procesamiento de imágenes PNG (formato donut)
- ✅ Procesamiento de PDFs
- ✅ Sin falsos positivos de descuentos
- ✅ Detección correcta de descuentos legítimos
- ✅ Validación matemática 100% precisa

---

## Archivos de Documentación

1. **`TEST_REPORT.md`** - Reporte completo de validación con resultados detallados
2. **`TECHNICAL_CHANGES.md`** - Resumen técnico de cambios implementados
3. **`test_results.json`** - Datos crudos de todos los tests ejecutados

---

## Cómo Usar el Pipeline

### 1. Procesar un Archivo Individual

```python
from src.modules.pipeline.service.pipeline import run_pipeline

# Procesar una imagen PNG
result = run_pipeline('/ruta/a/imagen.png')

# Procesar un PDF
result = run_pipeline('/ruta/a/documento.pdf')

# Ver el resultado
print(result['invoice'])
# {
#   'vendor_name': 'Acme Corp',
#   'invoice_date': '2025-01-15',
#   'total_cents': 10000,
#   'discount_cents': 0,
#   ...
# }
```

### 2. Verificar en Base de Datos

```python
from src.modules.pipeline.storage import db
from src.modules.pipeline.utils.files import compute_file_hash

# Obtener documento por hash
file_hash = compute_file_hash('/ruta/a/archivo.pdf')

with db.session_scope() as session:
    doc = session.query(db.Document).filter(
        db.Document.file_hash == file_hash
    ).first()
    
    print(f"Vendor: {doc.vendor_name}")
    print(f"Total: ${doc.total_cents/100:.2f}")
    print(f"Discount: ${doc.discount_cents/100:.2f}")
```

### 3. Limpiar Cache (Force Reprocessing)

```python
from src.modules.pipeline.storage import db
from src.modules.pipeline.utils.files import compute_file_hash

file_hash = compute_file_hash('/ruta/a/archivo.pdf')

with db.session_scope() as session:
    deleted = session.query(db.Document).filter(
        db.Document.file_hash == file_hash
    ).delete()
    print(f"Deleted {deleted} cached record(s)")

# Ahora al ejecutar run_pipeline() hará procesamiento completo
```

---

## Validación de Resultados

### Verificar que No Hay Descuentos Falsos

```python
import os
from src.modules.pipeline.service.pipeline import run_pipeline

# Procesar todos los archivos en un directorio
directory = '/home/simonll4/Desktop/ia/proyecto/ejes'
files = [f for f in os.listdir(directory) if f.endswith(('.png', '.pdf'))]

for filename in files:
    path = os.path.join(directory, filename)
    result = run_pipeline(path)
    
    discount = result['invoice']['discount_cents']
    if discount > 0:
        print(f"⚠️  {filename}: has discount=${discount/100:.2f}")
    else:
        print(f"✓ {filename}: no discount")
```

### Verificar Coherencia Matemática

```python
def verify_invoice_math(invoice_data):
    """Verifica que subtotal + tax - discount = total"""
    subtotal = invoice_data.get('subtotal_cents', 0)
    tax = invoice_data.get('tax_cents', 0)
    discount = invoice_data.get('discount_cents', 0)
    total = invoice_data.get('total_cents', 0)
    
    expected = subtotal + tax - discount
    diff = abs(expected - total)
    
    return {
        'is_valid': diff < 10,  # Tolerancia de 10 centavos
        'expected': expected,
        'actual': total,
        'difference': diff
    }

# Uso
result = run_pipeline('/ruta/a/archivo.pdf')
validation = verify_invoice_math(result['invoice'])

if validation['is_valid']:
    print("✓ Math is correct")
else:
    print(f"✗ Math error: diff=${validation['difference']/100:.2f}")
```

---

## Casos de Uso Comunes

### Caso 1: Procesar Lote de Facturas

```python
import os
from src.modules.pipeline.service.pipeline import run_pipeline

def process_batch(directory, file_extension='.pdf'):
    """Procesa todos los archivos de un directorio"""
    files = [f for f in os.listdir(directory) if f.endswith(file_extension)]
    results = []
    
    for filename in files:
        path = os.path.join(directory, filename)
        try:
            result = run_pipeline(path)
            results.append({
                'file': filename,
                'status': 'success',
                'vendor': result['invoice']['vendor_name'],
                'total': result['invoice']['total_cents'],
                'discount': result['invoice']['discount_cents']
            })
        except Exception as e:
            results.append({
                'file': filename,
                'status': 'error',
                'error': str(e)
            })
    
    return results

# Procesar PDFs
pdf_results = process_batch('/ruta/a/pdfs', '.pdf')

# Procesar imágenes
image_results = process_batch('/ruta/a/imagenes', '.png')
```

### Caso 2: Exportar a CSV

```python
import csv
import os
from src.modules.pipeline.service.pipeline import run_pipeline

def export_to_csv(directory, output_file='invoices.csv'):
    """Exporta facturas procesadas a CSV"""
    files = [f for f in os.listdir(directory) if f.endswith(('.pdf', '.png'))]
    
    with open(output_file, 'w', newline='') as csvfile:
        fieldnames = ['file', 'vendor', 'date', 'subtotal', 'tax', 'discount', 'total']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for filename in files:
            path = os.path.join(directory, filename)
            try:
                result = run_pipeline(path)
                inv = result['invoice']
                
                writer.writerow({
                    'file': filename,
                    'vendor': inv['vendor_name'],
                    'date': inv['invoice_date'],
                    'subtotal': inv.get('subtotal_cents', 0) / 100,
                    'tax': inv.get('tax_cents', 0) / 100,
                    'discount': inv.get('discount_cents', 0) / 100,
                    'total': inv['total_cents'] / 100
                })
            except Exception as e:
                print(f"Error processing {filename}: {e}")
    
    print(f"Exported to {output_file}")

# Uso
export_to_csv('/home/simonll4/Desktop/ia/proyecto/ejes', 'facturas_procesadas.csv')
```

### Caso 3: Consultar Facturas con Descuento

```python
from src.modules.pipeline.storage import db

def get_invoices_with_discount(min_discount_cents=0):
    """Obtiene todas las facturas que tienen descuento"""
    with db.session_scope() as session:
        docs = session.query(db.Document).filter(
            db.Document.discount_cents > min_discount_cents
        ).all()
        
        results = []
        for doc in docs:
            results.append({
                'vendor': doc.vendor_name,
                'date': doc.invoice_date,
                'total': doc.total_cents / 100,
                'discount': doc.discount_cents / 100,
                'discount_percentage': (doc.discount_cents / doc.total_cents * 100) if doc.total_cents > 0 else 0
            })
        
        return results

# Obtener facturas con descuento > $10
discounted = get_invoices_with_discount(min_discount_cents=1000)

for invoice in discounted:
    print(f"{invoice['vendor']}: total=${invoice['total']:.2f}, discount=${invoice['discount']:.2f} ({invoice['discount_percentage']:.1f}%)")
```

---

## Debugging y Troubleshooting

### Ver Texto OCR Extraído

```python
from src.modules.pipeline.storage import db
from src.modules.pipeline.utils.files import compute_file_hash

file_hash = compute_file_hash('/ruta/a/archivo.png')

with db.session_scope() as session:
    doc = session.query(db.Document).filter(
        db.Document.file_hash == file_hash
    ).first()
    
    if doc:
        print("RAW OCR TEXT:")
        print(doc.raw_text)
```

### Verificar Extracción de Resumen

```python
from src.modules.pipeline.service.pipeline import _extract_summary_values

# Simular con texto OCR
ocr_text = """
Invoice #12345
Subtotal: $100.00
Tax (10%): $10.00
Discount (20%): $20.00
Total: $90.00
"""

summary = _extract_summary_values(ocr_text)
print(summary)
# {'subtotal': 10000, 'addition': 1000, 'discount': 2000, 'total': 9000}
```

### Re-procesar con Logs Detallados

```python
import logging
from loguru import logger

# Activar logs detallados
logger.remove()  # Remover handler por defecto
logger.add(lambda msg: print(msg), level="DEBUG")

# Ahora ejecutar pipeline
result = run_pipeline('/ruta/a/archivo.pdf')
```

---

## Estructura de Respuesta

### Formato del Resultado

```python
{
  "schema_version": "invoice_v1",
  "invoice": {
    "invoice_number": "12345",
    "invoice_date": "2025-01-15",
    "vendor_name": "Acme Corporation",
    "vendor_tax_id": "12-3456789",
    "buyer_name": "John Doe",
    "currency_code": "USD",
    "subtotal_cents": 10000,      # $100.00
    "tax_cents": 1000,             # $10.00
    "total_cents": 11000,          # $110.00
    "discount_cents": 0            # $0.00
  },
  "items": [
    {
      "idx": 1,
      "description": "Product A",
      "qty": 2.0,
      "unit_price_cents": 5000,
      "line_total_cents": 10000,
      "category": "Electronics"
    }
  ],
  "notes": {
    "warnings": null,
    "confidence": 0.95
  }
}
```

---

## Contacto y Soporte

Si encuentras algún problema:

1. Revisa los logs del pipeline
2. Verifica el texto OCR extraído (puede haber errores de OCR)
3. Consulta `TEST_REPORT.md` para ver casos validados
4. Revisa `TECHNICAL_CHANGES.md` para entender la lógica implementada

---

**Última actualización**: 12 de Noviembre, 2025  
**Versión validada**: 100% funcional sobre 26 archivos de test
