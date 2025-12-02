"""
Test Suite for Password Security Features

Tests password strength validation and password reuse prevention.
"""

from utils.password_validator import validate_password_strength, has_sequential_numbers


def test_password_strength():
    """Test password strength validation"""
    print("\n" + "="*70)
    print("Testing Password Strength Validation")
    print("="*70 + "\n")
    
    test_cases = [
        # (password, should_pass, description)
        ("Short1@", False, "Too short (7 chars)"),
        ("NoSpecial1", False, "No special character"),
        ("noupperca$e1", False, "No uppercase letter"),
        ("NOLOWERCASE1@", False, "No lowercase letter"),
        ("Valid@Pass1", True, "Valid password (11 chars)"),
        ("MyP@ssw0rd", True, "Valid password (10 chars)"),
        ("Test123@Pass", False, "Contains sequential numbers (123)"),
        ("Pass@word456", False, "Contains sequential numbers (456)"),
        ("Pass@word789", False, "Contains sequential numbers (789)"),
        ("Pass@word987", False, "Contains descending sequence (987)"),
        ("Pass@word321", False, "Contains descending sequence (321)"),
        ("MySecure@P4ss", True, "Valid - non-sequential numbers"),
        ("C0mpl3x@Pass!", True, "Valid - complex password"),
        ("Short@1", False, "Too short (7 chars)"),
        ("ValidP@ss2024", False, "Contains sequential (2024 has 234)"),
        ("Str0ng!P@ssw0rd", True, "Valid - strong password"),
    ]
    
    passed = 0
    failed = 0
    
    for password, should_pass, description in test_cases:
        is_valid, error_msg = validate_password_strength(password)
        
        if is_valid == should_pass:
            status = "✅ PASS"
            passed += 1
        else:
            status = "❌ FAIL"
            failed += 1
        
        print(f"{status} | {description}")
        print(f"         Password: '{password}'")
        print(f"         Expected: {'Valid' if should_pass else 'Invalid'}")
        print(f"         Got: {'Valid' if is_valid else 'Invalid'}")
        if error_msg:
            print(f"         Error: {error_msg}")
        print()
    
    print("="*70)
    print(f"Results: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    print("="*70 + "\n")
    
    return failed == 0


def test_sequential_numbers():
    """Test sequential number detection"""
    print("\n" + "="*70)
    print("Testing Sequential Number Detection")
    print("="*70 + "\n")
    
    test_cases = [
        # (password, should_have_sequence, description)
        ("abc123def", True, "Contains 123"),
        ("test456pass", True, "Contains 456"),
        ("pass789word", True, "Contains 789"),
        ("word987test", True, "Contains 987 (descending)"),
        ("test321word", True, "Contains 321 (descending)"),
        ("pass135word", False, "Non-sequential (135)"),
        ("test246pass", False, "Non-sequential (246)"),
        ("word147test", False, "Non-sequential (147)"),
        ("nodigits", False, "No digits"),
        ("test12pass", False, "Only 2 consecutive digits"),
        ("pass2024word", True, "Contains 234 in 2024"),
        ("test2468pass", False, "Non-sequential (2468)"),
    ]
    
    passed = 0
    failed = 0
    
    for password, should_have_seq, description in test_cases:
        has_seq = has_sequential_numbers(password)
        
        if has_seq == should_have_seq:
            status = "✅ PASS"
            passed += 1
        else:
            status = "❌ FAIL"
            failed += 1
        
        print(f"{status} | {description}")
        print(f"         Password: '{password}'")
        print(f"         Expected: {'Has sequence' if should_have_seq else 'No sequence'}")
        print(f"         Got: {'Has sequence' if has_seq else 'No sequence'}")
        print()
    
    print("="*70)
    print(f"Results: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    print("="*70 + "\n")
    
    return failed == 0


if __name__ == '__main__':
    print("\n" + "🔐 PASSWORD SECURITY TEST SUITE ".center(70, "="))
    
    all_passed = True
    
    # Run tests
    if not test_password_strength():
        all_passed = False
    
    if not test_sequential_numbers():
        all_passed = False
    
    # Final summary
    print("\n" + "="*70)
    if all_passed:
        print("✅ ALL TESTS PASSED!")
    else:
        print("❌ SOME TESTS FAILED - Please review the output above")
    print("="*70 + "\n")
