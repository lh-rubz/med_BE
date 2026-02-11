"""Test categorical range handling for HbA1c-style ranges."""
import sys
sys.path.append(r'd:\med_BE')

from utils.medical_validator import MedicalValidator

def test_hba1c_categorical():
    """Test the HbA1c range: Normal: less than 5.7 % Prediabetes: 5.7 - 6.4 % Diabetes: > 6.5 %"""
    hba1c_range = "Normal: less than 5.7 % Prediabetes: 5.7 - 6.4 % Diabetes: > 6.5 %"
    
    tests = [
        ("5.1", True, "Normal (5.1 < 5.7)"),
        ("4.0", True, "Normal (4.0 < 5.7)"),
        ("5.6", True, "Normal (5.6 < 5.7)"),
        ("5.7", False, "Prediabetes (5.7 in 5.7-6.4)"),
        ("6.0", False, "Prediabetes (6.0 in 5.7-6.4)"),
        ("6.4", False, "Prediabetes (6.4 in 5.7-6.4)"),
        ("7.0", False, "Diabetes (7.0 > 6.5)"),
        ("10.0", False, "Diabetes (10.0 > 6.5)"),
    ]
    
    passed = 0
    failed = 0
    for value, expected, description in tests:
        result = MedicalValidator.calculate_is_normal(value, hba1c_range)
        status = "✅" if result == expected else "❌"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status} HbA1c={value}: is_normal={result} (expected={expected}) — {description}")
    
    print(f"\n  Results: {passed}/{passed+failed} passed")
    return failed == 0

def test_simple_categorical():
    """Test simpler categorical ranges."""
    vit_d_range = "Deficient: <10, Insufficient: 10-30, Sufficient: 31-100, Toxic: >100"
    
    tests = [
        ("5", False, "Deficient"),
        ("15", False, "Insufficient"),
        ("50", True, "Sufficient"),
        ("120", False, "Toxic"),
    ]
    
    passed = 0
    for value, expected, description in tests:
        result = MedicalValidator.calculate_is_normal(value, vit_d_range)
        status = "✅" if result == expected else "❌"
        if result == expected:
            passed += 1
        print(f"  {status} VitD={value}: is_normal={result} (expected={expected}) — {description}")
    
    print(f"\n  Results: {passed}/{len(tests)} passed")
    return passed == len(tests)

if __name__ == "__main__":
    print("=" * 60)
    print("Test 1: HbA1c Categorical Range")
    print("=" * 60)
    t1 = test_hba1c_categorical()
    
    print()
    print("=" * 60)
    print("Test 2: Vitamin D Categorical Range")
    print("=" * 60)
    t2 = test_simple_categorical()
    
    print()
    if t1 and t2:
        print("🎉 ALL TESTS PASSED")
    else:
        print("⚠️ SOME TESTS FAILED")
