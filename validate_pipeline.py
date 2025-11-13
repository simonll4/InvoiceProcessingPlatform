#!/usr/bin/env python3
"""
Quick Validation Script - Pipeline Health Check
Run this script to verify the pipeline is working correctly.
"""

import sys
import os

# Add project to path
sys.path.insert(0, '/home/simonll4/Desktop/ia/proyecto/pipeline-python')

from src.modules.pipeline.service.pipeline import run_pipeline
from src.modules.pipeline.storage import db
from src.modules.pipeline.utils.files import compute_file_hash

def clear_cache(file_path):
    """Clear cache for a specific file to force reprocessing."""
    file_hash = compute_file_hash(file_path)
    with db.session_scope() as session:
        deleted = session.query(db.Document).filter(
            db.Document.file_hash == file_hash
        ).delete()
    return deleted

def test_png_image():
    """Test PNG image processing (should have discount=0)."""
    print("\n" + "="*80)
    print("TEST 1: PNG Image Processing (No Discount Expected)")
    print("="*80)
    
    test_file = '/home/simonll4/Desktop/ia/proyecto/ejes/donut_train_0000.png'
    
    if not os.path.exists(test_file):
        print("❌ SKIP: Test file not found")
        return False
    
    # Clear cache
    clear_cache(test_file)
    
    # Process
    result = run_pipeline(test_file)
    invoice = result['invoice']
    
    # Validate
    has_discount = invoice['discount_cents'] > 0
    
    print(f"  Vendor: {invoice['vendor_name']}")
    print(f"  Total: ${invoice['total_cents']/100:.2f}")
    print(f"  Discount: ${invoice['discount_cents']/100:.2f}")
    
    if has_discount:
        print("  ❌ FAIL: Unexpected discount detected!")
        return False
    else:
        print("  ✅ PASS: No false positive discount")
        return True

def test_pdf_with_discount():
    """Test PDF with legitimate discount."""
    print("\n" + "="*80)
    print("TEST 2: PDF Processing (Discount Expected)")
    print("="*80)
    
    test_file = '/home/simonll4/Desktop/ia/proyecto/ejes/invoice_Allen Rosenblatt_33571.pdf'
    
    if not os.path.exists(test_file):
        print("❌ SKIP: Test file not found")
        return False
    
    # Clear cache
    clear_cache(test_file)
    
    # Process
    result = run_pipeline(test_file)
    invoice = result['invoice']
    
    # Validate math
    subtotal = invoice.get('subtotal_cents', 0)
    tax = invoice.get('tax_cents', 0)
    discount = invoice.get('discount_cents', 0)
    total = invoice.get('total_cents', 0)
    
    expected_total = subtotal + tax - discount
    diff = abs(expected_total - total)
    
    print(f"  Vendor: {invoice['vendor_name']}")
    print(f"  Subtotal: ${subtotal/100:.2f}")
    print(f"  Tax: ${tax/100:.2f}")
    print(f"  Discount: ${discount/100:.2f}")
    print(f"  Total: ${total/100:.2f}")
    print(f"  Math check: {expected_total} == {total} (diff={diff})")
    
    # Check OCR contains discount keyword
    file_hash = compute_file_hash(test_file)
    with db.session_scope() as session:
        doc = session.query(db.Document).filter(
            db.Document.file_hash == file_hash
        ).first()
        has_keyword = 'discount' in (doc.raw_text or '').lower() if doc else False
    
    print(f"  Discount keyword in OCR: {has_keyword}")
    
    if diff >= 10:
        print("  ❌ FAIL: Math doesn't add up!")
        return False
    elif not has_keyword:
        print("  ❌ FAIL: No discount keyword found in OCR")
        return False
    elif discount == 0:
        print("  ❌ FAIL: Discount should be detected")
        return False
    else:
        print("  ✅ PASS: Discount correctly detected and calculated")
        return True

def test_cache_mechanism():
    """Test that cache works correctly."""
    print("\n" + "="*80)
    print("TEST 3: Cache Mechanism")
    print("="*80)
    
    test_file = '/home/simonll4/Desktop/ia/proyecto/ejes/donut_train_0001.png'
    
    if not os.path.exists(test_file):
        print("❌ SKIP: Test file not found")
        return False
    
    # First run (fresh)
    file_hash = compute_file_hash(test_file)
    clear_cache(test_file)
    result1 = run_pipeline(test_file)
    
    # Verify it was saved to DB
    with db.session_scope() as session:
        doc = session.query(db.Document).filter(
            db.Document.file_hash == file_hash
        ).first()
        first_run_saved = doc is not None
    
    # Second run (should hit cache - no new DB insert)
    result2 = run_pipeline(test_file)
    
    # Results should be identical
    results_match = result1 == result2
    
    print(f"  First run: {'saved to DB ✓' if first_run_saved else 'not saved ✗'}")
    print(f"  Second run: completed")
    print(f"  Results match: {results_match}")
    
    if first_run_saved and results_match:
        print("  ✅ PASS: Cache working correctly")
        return True
    else:
        print("  ❌ FAIL: Cache not working")
        return False

def main():
    """Run all validation tests."""
    print("\n" + "="*80)
    print("PIPELINE VALIDATION - QUICK HEALTH CHECK")
    print("="*80)
    
    results = []
    
    try:
        results.append(("PNG Processing", test_png_image()))
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append(("PNG Processing", False))
    
    try:
        results.append(("PDF Processing", test_pdf_with_discount()))
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append(("PDF Processing", False))
    
    try:
        results.append(("Cache Mechanism", test_cache_mechanism()))
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results.append(("Cache Mechanism", False))
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED - PIPELINE IS HEALTHY!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} TEST(S) FAILED - CHECK LOGS ABOVE")
        return 1

if __name__ == '__main__':
    sys.exit(main())
