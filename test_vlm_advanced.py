"""
Test suite for advanced VLM extraction system.

This module tests all the improvements made to the VLM system,
focusing on the bugs found in the original report.
"""

import unittest
from datetime import datetime
from utils.vlm_integration_advanced import VLMExtractionValidator


class TestVLMGenderConversion(unittest.TestCase):
    """Test gender conversion from Arabic to English."""
    
    def setUp(self):
        self.validator = VLMExtractionValidator()
    
    def test_arabic_male_conversion(self):
        """Test conversion of Arabic 'ذكر' to 'Male'"""
        self.assertEqual(self.validator.validate_gender('ذكر'), 'Male')
        self.assertEqual(self.validator.validate_gender('ذكور'), 'Male')
        self.assertEqual(self.validator.validate_gender(' ذكر '), 'Male')
    
    def test_arabic_female_conversion(self):
        """Test conversion of Arabic 'أنثى' to 'Female'"""
        self.assertEqual(self.validator.validate_gender('أنثى'), 'Female')
        self.assertEqual(self.validator.validate_gender('انثى'), 'Female')
        self.assertEqual(self.validator.validate_gender('انثي'), 'Female')
    
    def test_english_male_conversion(self):
        """Test English male values"""
        self.assertEqual(self.validator.validate_gender('Male'), 'Male')
        self.assertEqual(self.validator.validate_gender('male'), 'Male')
        self.assertEqual(self.validator.validate_gender('M'), 'Male')
    
    def test_english_female_conversion(self):
        """Test English female values"""
        self.assertEqual(self.validator.validate_gender('Female'), 'Female')
        self.assertEqual(self.validator.validate_gender('female'), 'Female')
        self.assertEqual(self.validator.validate_gender('F'), 'Female')
    
    def test_invalid_gender(self):
        """Test invalid gender returns empty string"""
        self.assertEqual(self.validator.validate_gender(''), '')
        self.assertEqual(self.validator.validate_gender('Invalid'), '')
        self.assertEqual(self.validator.validate_gender(None), '')
    
    def test_never_returns_arabic(self):
        """Test that output never contains Arabic gender text"""
        outputs = [
            self.validator.validate_gender('ذكر'),
            self.validator.validate_gender('أنثى'),
            self.validator.validate_gender('ذكور'),
            self.validator.validate_gender('انثى')
        ]
        
        for output in outputs:
            self.assertNotIn('ذكر', output, "Output should never contain Arabic 'ذكر'")
            self.assertNotIn('أنثى', output, "Output should never contain Arabic 'أنثى'")


class TestVLMAgeCalculation(unittest.TestCase):
    """Test age calculation from DOB."""
    
    def setUp(self):
        self.validator = VLMExtractionValidator()
    
    def test_dob_01_05_1975(self):
        """
        Test case from the bug report.
        DOB: 01/05/1975 should calculate to ~50 years, NOT 28.
        """
        # Test with different format interpretations
        # European format: 01/05/1975 = May 1, 1975
        age_eu = self.validator.calculate_age('01/05/1975')
        
        # Should be approximately 50-51 years old (depending on current date)
        age_numeric = int(age_eu) if age_eu else 0
        self.assertGreaterEqual(age_numeric, 49, 
                              f"Age from 01/05/1975 should be ~50, got {age_numeric}")
        self.assertLessEqual(age_numeric, 52,
                           f"Age from 01/05/1975 should be ~50, got {age_numeric}")
        
        # Should NOT be 28
        self.assertNotEqual(age_numeric, 28, "Age should not be 28 for DOB 01/05/1975")
    
    def test_dob_american_format(self):
        """Test American format MM/DD/YYYY"""
        # 05/01/1975 = May 1, 1975
        age = self.validator.calculate_age('05/01/1975')
        age_numeric = int(age) if age else 0
        self.assertGreaterEqual(age_numeric, 49)
        self.assertLessEqual(age_numeric, 52)
    
    def test_dob_iso_format(self):
        """Test ISO format YYYY-MM-DD"""
        age = self.validator.calculate_age('1975-05-01')
        age_numeric = int(age) if age else 0
        self.assertGreaterEqual(age_numeric, 49)
        self.assertLessEqual(age_numeric, 52)
    
    def test_dob_with_dots(self):
        """Test format with dots: DD.MM.YYYY"""
        age = self.validator.calculate_age('01.05.1975')
        age_numeric = int(age) if age else 0
        self.assertGreaterEqual(age_numeric, 49)
        self.assertLessEqual(age_numeric, 52)
    
    def test_invalid_dob(self):
        """Test invalid DOB returns empty string"""
        self.assertEqual(self.validator.calculate_age(''), '')
        self.assertEqual(self.validator.calculate_age('invalid'), '')
        self.assertEqual(self.validator.calculate_age(None), '')
    
    def test_unrealistic_age(self):
        """Test that unrealistic ages are rejected"""
        # 200 years old
        age = self.validator.calculate_age('01/01/1800')
        self.assertEqual(age, '', "Age > 130 should return empty string")
        
        # Negative age (future date)
        age = self.validator.calculate_age('01/01/2100')
        self.assertEqual(age, '', "Future date should return empty string")
    
    def test_age_as_string(self):
        """Test that age is returned as string"""
        age = self.validator.calculate_age('01/05/1975')
        self.assertIsInstance(age, str, "Age should be returned as string")


class TestVLMDOBNormalization(unittest.TestCase):
    """Test DOB normalization to YYYY-MM-DD format."""
    
    def setUp(self):
        self.validator = VLMExtractionValidator()
    
    def test_european_format(self):
        """Test DD/MM/YYYY → YYYY-MM-DD"""
        result = self.validator.normalize_dob('01/05/1975')
        self.assertEqual(result, '1975-05-01')
    
    def test_american_format(self):
        """Test MM/DD/YYYY → YYYY-MM-DD"""
        result = self.validator.normalize_dob('05/01/1975')
        self.assertEqual(result, '1975-01-05')
    
    def test_iso_format_unchanged(self):
        """Test YYYY-MM-DD stays the same"""
        result = self.validator.normalize_dob('1975-05-01')
        self.assertEqual(result, '1975-05-01')
    
    def test_dob_with_dashes(self):
        """Test DD-MM-YYYY format"""
        result = self.validator.normalize_dob('01-05-1975')
        self.assertEqual(result, '1975-05-01')
    
    def test_dob_with_dots(self):
        """Test DD.MM.YYYY format"""
        result = self.validator.normalize_dob('01.05.1975')
        self.assertEqual(result, '1975-05-01')
    
    def test_invalid_dob_normalization(self):
        """Test invalid DOB returns empty string"""
        self.assertEqual(self.validator.normalize_dob(''), '')
        self.assertEqual(self.validator.normalize_dob('invalid'), '')
        self.assertEqual(self.validator.normalize_dob('32/13/2000'), '')


class TestVLMDateNormalization(unittest.TestCase):
    """Test report date normalization."""
    
    def setUp(self):
        self.validator = VLMExtractionValidator()
    
    def test_remove_timestamp(self):
        """Test removal of timestamp from date"""
        # This is the exact issue from the bug report
        result = self.validator.normalize_date('2025-12-31 10:00:02.0')
        self.assertEqual(result, '2025-12-31',
                        "Timestamp should be removed from date")
    
    def test_just_date(self):
        """Test date without timestamp"""
        result = self.validator.normalize_date('2025-12-31')
        self.assertEqual(result, '2025-12-31')
    
    def test_european_date_format(self):
        """Test DD/MM/YYYY format"""
        result = self.validator.normalize_date('31/12/2025')
        self.assertEqual(result, '2025-12-31')
    
    def test_american_date_format(self):
        """Test MM/DD/YYYY format"""
        result = self.validator.normalize_date('12/31/2025')
        self.assertEqual(result, '2025-12-31')
    
    def test_invalid_date(self):
        """Test invalid date"""
        self.assertEqual(self.validator.normalize_date(''), '')
        self.assertEqual(self.validator.normalize_date('invalid'), '')


class TestVLMPersonalInfoValidation(unittest.TestCase):
    """Test complete personal info validation."""
    
    def setUp(self):
        self.validator = VLMExtractionValidator()
    
    def test_validation_with_bug_report_data(self):
        """
        Test with actual data from the bug report.
        
        Original extracted data (WRONG):
        - patient_name: رئيسي خضر طالب خطيب
        - patient_age: 28 ← WRONG!
        - patient_dob: 01/05/1975
        - patient_gender: Male (but said Female in images) ← WRONG!
        - report_date: 2026-01-23 20:50:51.129476 ← Contains timestamp!
        - doctor_names: (empty) ← WRONG, should be found!
        """
        raw_data = {
            'patient_name': 'رئيسي خضر طالب خطيب',
            'patient_age': '28',  # Wrong
            'patient_dob': '01/05/1975',
            'patient_gender': 'ذكر',  # Arabic, should convert
            'report_date': '2026-01-23 20:50:51.129476',  # Has timestamp
            'doctor_names': ''
        }
        
        validated = self.validator.validate_personal_info(raw_data)
        
        # Check corrections
        self.assertEqual(validated['patient_name'], 'رئيسي خضر طالب خطيب',
                        "Patient name should be preserved")
        
        # Age should be recalculated from DOB
        age_numeric = int(validated['patient_age']) if validated['patient_age'] else 0
        self.assertGreaterEqual(age_numeric, 49, 
                              "Age should be recalculated to ~50, not 28")
        self.assertNotEqual(age_numeric, 28, "Age must not be 28")
        
        # DOB should be normalized
        self.assertEqual(validated['patient_dob'], '1975-05-01',
                        "DOB should be in YYYY-MM-DD format")
        
        # Gender must be English
        self.assertEqual(validated['patient_gender'], 'Male',
                        "Gender should be converted to English 'Male'")
        self.assertNotIn('ذكر', validated['patient_gender'],
                        "Gender should not contain Arabic")
        
        # Date should not have timestamp
        self.assertEqual(validated['report_date'], '2026-01-23',
                        "Report date should not contain timestamp")
    
    def test_facility_name_rejection(self):
        """Test that facility names are rejected as patient names."""
        data = {'patient_name': 'Laboratory(Ramallah PHC)'}
        validated = self.validator.validate_personal_info(data)
        self.assertEqual(validated['patient_name'], '',
                        "Facility names should not be accepted as patient name")
    
    def test_valid_person_name(self):
        """Test that valid person names are accepted."""
        data = {'patient_name': 'Ahmed Mohammed Hassan'}
        validated = self.validator.validate_personal_info(data)
        self.assertEqual(validated['patient_name'], 'Ahmed Mohammed Hassan',
                        "Valid person names should be accepted")


class TestVLMMisalignmentDetection(unittest.TestCase):
    """Test detection of misaligned medical data rows."""
    
    def setUp(self):
        self.validator = VLMExtractionValidator()
    
    def test_value_contains_unit_symbol(self):
        """Test detection when value contains unit symbols."""
        data = [
            {
                'field_name': 'Glucose',
                'field_value': '109%',  # Wrong: contains %
                'field_unit': 'mg/dL',
                'normal_range': '(70-110)'
            }
        ]
        
        issues = self.validator.detect_misaligned_rows(data)
        self.assertTrue(any('unit symbol' in issue[1] for issue in issues),
                       "Should detect unit symbol in value")
    
    def test_value_is_range(self):
        """Test detection when value looks like a range."""
        data = [
            {
                'field_name': 'ALT',
                'field_value': '(0-33)',  # Wrong: looks like range
                'field_unit': 'U/L',
                'normal_range': '32'
            }
        ]
        
        issues = self.validator.detect_misaligned_rows(data)
        self.assertTrue(any('range' in issue[1] for issue in issues),
                       "Should detect range in value")
    
    def test_unit_is_number(self):
        """Test detection when unit is a number."""
        data = [
            {
                'field_name': 'ALT',
                'field_value': 'U/L',  # Wrong: unit value swapped
                'field_unit': '320',   # Wrong: numeric value
                'normal_range': '(0-33)'
            }
        ]
        
        issues = self.validator.detect_misaligned_rows(data)
        self.assertTrue(any('numeric' in issue[1] for issue in issues),
                       "Should detect numeric unit (likely swapped)")
    
    def test_correct_alignment(self):
        """Test that correct alignment is not flagged."""
        data = [
            {
                'field_name': 'ALT',
                'field_value': '32',
                'field_unit': 'U/L',
                'normal_range': '(0-33)'
            }
        ]
        
        issues = self.validator.detect_misaligned_rows(data)
        self.assertEqual(len(issues), 0, "Correct alignment should not be flagged")


if __name__ == '__main__':
    unittest.main()
