#!/usr/bin/env python3
"""
Script para limpiar el cache del pipeline.

Uso:
    python clear_cache.py                    # Limpia TODO el cache
    python clear_cache.py --invoice 40378170 # Limpia una factura específica
    python clear_cache.py --file path.png    # Limpia por archivo específico
"""

import sys
import argparse
import sqlite3
from pathlib import Path

# Agregar el directorio del proyecto al path
sys.path.insert(0, str(Path(__file__).parent))

from src.modules.pipeline.storage import db
from src.modules.pipeline.utils.files import compute_file_hash


def clear_all_cache():
    """Elimina TODO el cache y la base de datos."""
    db_path = Path('data/app.db')
    if db_path.exists():
        db_path.unlink()
        print("✅ Cache completo eliminado (data/app.db borrado)")
    else:
        print("ℹ️  No hay cache para eliminar")


def clear_by_invoice_number(invoice_number: str):
    """Elimina cache de una factura específica por número."""
    # Limpiar de la tabla Document
    with db.session_scope() as s:
        deleted_docs = s.query(db.Document).filter(
            db.Document.raw_json.like(f'%"invoice_number": "{invoice_number}"%')
        ).delete(synchronize_session=False)
    
    # Limpiar de la tabla invoices
    conn = sqlite3.connect('data/app.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM invoices WHERE invoice_number = ?", (invoice_number,))
    deleted_inv = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"✅ Eliminadas {deleted_docs} entradas de Document y {deleted_inv} de invoices para factura #{invoice_number}")


def clear_by_file(file_path: str):
    """Elimina cache de un archivo específico."""
    file_hash = compute_file_hash(file_path)
    
    with db.session_scope() as s:
        deleted = s.query(db.Document).filter(db.Document.file_hash == file_hash).delete()
    
    print(f"✅ Eliminadas {deleted} entradas para archivo: {file_path}")
    print(f"   File hash: {file_hash}")


def main():
    parser = argparse.ArgumentParser(description='Limpiar cache del pipeline de facturas')
    parser.add_argument('--all', action='store_true', help='Eliminar TODO el cache')
    parser.add_argument('--invoice', type=str, help='Número de factura a eliminar')
    parser.add_argument('--file', type=str, help='Ruta del archivo a eliminar del cache')
    
    args = parser.parse_args()
    
    if args.all:
        clear_all_cache()
    elif args.invoice:
        clear_by_invoice_number(args.invoice)
    elif args.file:
        clear_by_file(args.file)
    else:
        # Si no se especifica nada, mostrar ayuda
        parser.print_help()
        print("\n💡 Ejemplos:")
        print("  python clear_cache.py --all")
        print("  python clear_cache.py --invoice 40378170")
        print("  python clear_cache.py --file data/uploads/abc.png")


if __name__ == '__main__':
    main()
