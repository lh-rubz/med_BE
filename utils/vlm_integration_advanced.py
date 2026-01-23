"""Integration module for advanced VLM extraction with intelligent validation."""

import json
import re
from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional


class VLMExtractionValidator:
    """Validates and corrects VLM extraction results."""
    
    @staticmethod
    def validate_gender(gender_str: str) -> str:
        """
        Validate and convert gender to English.
        Returns: "Male", "Female", or ""
        """
        if not gender_str:
            return ""
        
        gender = gender_str.strip()
        
        # Arabic conversions
        if gender in ["ذكر", "ذكور", "male arabic"]:
            return "Male"
        if gender in ["أنثى", "انثى", "انثي", "أنثي"]:
            return "Female"
        
        # English values
        if gender.lower() in ["male", "m"]:
            return "Male"
        if gender.lower() in ["female", "f", "fem"]:
            return "Female"
        
        # Already correct
        if gender in ["Male", "Female"]:
            return gender
        
        return ""
    
    @staticmethod
    def calculate_age(dob_str: str) -> str:
        """
        Calculate age from DOB in various formats.
        Handles: DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD, DD-MM-YYYY, DD.MM.YYYY
        """
        if not dob_str or not isinstance(dob_str, str):
            return ""
        
        dob_str = dob_str.strip()
        date_obj = None
        
        # Try parsing different formats
        formats = [
            '%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%d', '%d-%m-%Y', 
            '%d.%m.%Y', '%Y/%m/%d', '%d/%m/%y', '%m/%d/%y'
        ]
        
        for fmt in formats:
            try:
                date_obj = datetime.strptime(dob_str, fmt)
                break
            except ValueError:
                continue
        
        if not date_obj:
            return ""
        
        # Calculate age
        today = datetime.now()
        age = today.year - date_obj.year
        
        # Adjust for whether birthday has occurred this year
        if (today.month, today.day) < (date_obj.month, date_obj.day):
            age -= 1
        
        # Validate age range
        if 0 <= age <= 130:
            return str(age)
        
        return ""
    
    @staticmethod
    def normalize_dob(dob_str: str) -> str:
        """
        Convert DOB to YYYY-MM-DD format.
        Handles multiple input formats.
        """
        if not dob_str or not isinstance(dob_str, str):
            return ""
        
        dob_str = dob_str.strip()
        
        formats = [
            ('%d/%m/%Y', 'DD/MM/YYYY'),
            ('%m/%d/%Y', 'MM/DD/YYYY'),
            ('%Y-%m-%d', 'YYYY-MM-DD'),
            ('%d-%m-%Y', 'DD-MM-YYYY'),
            ('%d.%m.%Y', 'DD.MM.YYYY'),
            ('%Y/%m/%d', 'YYYY/MM/DD'),
            ('%d/%m/%y', 'DD/MM/YY'),
            ('%m/%d/%y', 'MM/DD/YY'),
        ]
        
        for fmt, _ in formats:
            try:
                date_obj = datetime.strptime(dob_str, fmt)
                return date_obj.strftime('%Y-%m-%d')
            except ValueError:
                continue
        
        return ""
    
    @staticmethod
    def normalize_date(date_str: str) -> str:
        """
        Extract date from timestamp and convert to YYYY-MM-DD.
        Remove time portion if present.
        """
        if not date_str or not isinstance(date_str, str):
            return ""
        
        date_str = date_str.strip()
        
        # Remove timestamp part if present
        date_only = date_str.split(' ')[0]
        
        # Try parsing
        formats = [
            '%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%d', '%d-%m-%Y',
            '%d.%m.%Y', '%Y/%m/%d'
        ]
        
        for fmt in formats:
            try:
                date_obj = datetime.strptime(date_only, fmt)
                return date_obj.strftime('%Y-%m-%d')
            except ValueError:
                continue
        
        return ""
    
    @staticmethod
    def validate_personal_info(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and correct personal information extraction.
        """
        validated = {}
        
        # Patient name
        name = str(data.get('patient_name', '')).strip()
        if name and len(name) >= 3:
            # Check for facility/lab keywords
            facility_keywords = ['facility', 'جهاز', 'treatment', 'lab', 'clinic', 
                               'hospital', 'مختبر', 'phc', 'equipment']
            if not any(kw.lower() in name.lower() for kw in facility_keywords):
                validated['patient_name'] = name
            else:
                validated['patient_name'] = ""
        else:
            validated['patient_name'] = ""
        
        # Gender (with validation and conversion)
        gender = data.get('patient_gender', '')
        validated['patient_gender'] = VLMExtractionValidator.validate_gender(gender)
        
        # DOB and Age
        dob = data.get('patient_dob', '')
        age = data.get('patient_age', '')
        
        # Normalize DOB
        normalized_dob = VLMExtractionValidator.normalize_dob(dob)
        validated['patient_dob'] = normalized_dob
        
        # Age: Use provided age if valid, otherwise calculate from DOB
        # CRITICAL: If provided age seems wrong (doesn't match DOB), recalculate from DOB
        if age and str(age).isdigit() and 1 <= int(age) <= 130:
            age_numeric = int(age)
            # If we have DOB, verify age matches DOB
            if normalized_dob:
                calculated_age = VLMExtractionValidator.calculate_age(normalized_dob)
                calculated_numeric = int(calculated_age) if calculated_age else 0
                # If provided age differs from calculated by more than 2 years, use calculated
                if abs(age_numeric - calculated_numeric) > 2:
                    validated['patient_age'] = calculated_age
                else:
                    validated['patient_age'] = str(age_numeric)
            else:
                validated['patient_age'] = str(age_numeric)
        elif normalized_dob:
            calculated_age = VLMExtractionValidator.calculate_age(normalized_dob)
            validated['patient_age'] = calculated_age
        else:
            validated['patient_age'] = ""
        
        # Report date
        report_date = data.get('report_date', '')
        validated['report_date'] = VLMExtractionValidator.normalize_date(report_date)
        
        # Doctor names
        doctor = str(data.get('doctor_names', '')).strip()
        validated['doctor_names'] = doctor if len(doctor) >= 3 else ""
        
        return validated
    
    @staticmethod
    def detect_misaligned_rows(medical_data: List[Dict[str, Any]]) -> List[Tuple[int, str]]:
        """
        Detect potentially misaligned rows in medical data.
        Returns: List of (index, reason) tuples
        """
        issues = []
        unit_symbols = ['%', 'K/uL', 'M/uL', 'mg/dL', 'mg/dl', 'U/L', 'cells/L', 
                       'g/dL', 'g/dl', 'mmol/L', 'μm', 'fl', 'pg']
        
        for idx, row in enumerate(medical_data):
            field_value = str(row.get('field_value', '')).strip()
            field_unit = str(row.get('field_unit', '')).strip()
            normal_range = str(row.get('normal_range', '')).strip()
            
            # Check if value contains unit symbols
            if field_value:
                for symbol in unit_symbols:
                    if symbol in field_value:
                        issues.append((idx, f"field_value contains unit symbol '{symbol}'"))
                        break
            
            # Check if value is a range
            if field_value and re.match(r'^\(\d+[-\.]\d+\)$', field_value):
                issues.append((idx, "field_value looks like a range"))
            
            # Check if unit is a number or range
            if field_unit:
                if field_unit.isdigit():
                    issues.append((idx, "field_unit is numeric (likely swapped)"))
                elif re.match(r'^\(\d+[-\.]\d+\)$', field_unit):
                    issues.append((idx, "field_unit is a range (likely swapped)"))
            
            # Check if range is a single number
            if normal_range and not normal_range.startswith('('):
                if normal_range.replace('.', '').isdigit():
                    issues.append((idx, "normal_range is a single number, not a range"))
        
        return issues
    
    @staticmethod
    def validate_medical_data(medical_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate medical data extraction.
        """
        validation_result = {
            'total_rows': len(medical_data),
            'rows_with_values': sum(1 for row in medical_data 
                                    if row.get('field_value', '').strip()),
            'rows_with_ranges': sum(1 for row in medical_data 
                                   if row.get('normal_range', '').strip()),
            'misaligned_rows': VLMExtractionValidator.detect_misaligned_rows(medical_data),
            'empty_field_names': sum(1 for row in medical_data 
                                    if not row.get('field_name', '').strip()),
            'is_valid': True
        }
        
        # Check if minimum threshold is met
        if validation_result['total_rows'] < 5:
            validation_result['is_valid'] = False
            validation_result['reason'] = 'Fewer than 5 rows extracted'
        
        # Check for misaligned rows
        if validation_result['misaligned_rows']:
            validation_result['is_valid'] = False
            validation_result['reason'] = f"{len(validation_result['misaligned_rows'])} misaligned rows detected"
        
        return validation_result


class AdvancedVLMExtractor:
    """Manages advanced VLM extraction with validation and multi-page support."""
    
    def __init__(self):
        self.validator = VLMExtractionValidator()
        self.extraction_history = []
    
    def process_personal_info(self, raw_extraction: Dict[str, Any]) -> Dict[str, Any]:
        """Process and validate personal info extraction."""
        return self.validator.validate_personal_info(raw_extraction)
    
    def process_medical_data(self, raw_extraction: Dict[str, Any]) -> Dict[str, Any]:
        """Process and validate medical data extraction."""
        medical_data = raw_extraction.get('medical_data', [])
        
        # Validate
        validation = self.validator.validate_medical_data(medical_data)
        
        return {
            'medical_data': medical_data,
            'validation': validation
        }
    
    def should_reextract(self, validation_result: Dict[str, Any]) -> bool:
        """Determine if extraction needs to be redone."""
        if not validation_result.get('is_valid'):
            return True
        
        # If fewer than expected rows and no misalignment
        if validation_result.get('total_rows', 0) < 10:
            return True  # Likely incomplete
        
        return False
    
    def log_extraction(self, page: int, data: Dict[str, Any], status: str = "success"):
        """Log extraction for tracking."""
        self.extraction_history.append({
            'page': page,
            'timestamp': datetime.now().isoformat(),
            'status': status,
            'data': data
        })


def create_integrated_extraction_prompt(page_idx: int, total_pages: int, 
                                       extraction_type: str = 'personal_info',
                                       previous_validation: Optional[Dict] = None) -> str:
    """
    Create optimized prompt based on extraction type and history.
    
    Args:
        page_idx: Current page number
        total_pages: Total pages
        extraction_type: 'personal_info' or 'medical_data'
        previous_validation: Previous validation results to guide correction
    
    Returns:
        Optimized prompt string
    """
    from utils.vlm_prompts_advanced import (
        get_advanced_personal_info_prompt,
        get_advanced_medical_data_prompt,
        get_advanced_page_verification_prompt
    )
    
    if extraction_type == 'personal_info':
        return get_advanced_personal_info_prompt(page_idx, total_pages)
    elif extraction_type == 'medical_data':
        prompt = get_advanced_medical_data_prompt(page_idx, total_pages)
        
        # Add context about previous validation
        if previous_validation:
            context = f"\n\n🔔 PREVIOUS EXTRACTION FEEDBACK:\n"
            if not previous_validation.get('is_valid'):
                context += f"Issues found: {previous_validation.get('reason', 'Unknown')}\n"
                if previous_validation.get('misaligned_rows'):
                    context += f"Misaligned row indices: {[r[0] for r in previous_validation['misaligned_rows']]}\n"
            context += "Please re-check these areas and correct the alignment.\n\n"
            prompt += context
        
        return prompt
    elif extraction_type == 'verification':
        return get_advanced_page_verification_prompt(page_idx, total_pages)
    
    return ""


if __name__ == "__main__":
    # Test the validator
    test_data = {
        'patient_name': 'رئيسي خضر طالب خطيب',
        'patient_age': '28',
        'patient_dob': '01/05/1975',
        'patient_gender': 'ذكر',
        'report_date': '2025-12-31 10:00:02.0',
        'doctor_names': 'Dr. جهاد العملة'
    }
    
    validator = VLMExtractionValidator()
    validated = validator.validate_personal_info(test_data)
    
    print("Original:", test_data)
    print("\nValidated:", validated)
    print("\nAge calculation test:")
    print(f"  DOB: 01/05/1975 -> Age: {validator.calculate_age('01/05/1975')}")
    print(f"  Gender conversion: ذكر -> {validator.validate_gender('ذكر')}")
    print(f"  Gender conversion: أنثى -> {validator.validate_gender('أنثى')}")
