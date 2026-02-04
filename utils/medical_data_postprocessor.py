"""
Post-processing utilities for VLM extracted medical data.
Handles validation, cleanup, and structure-aware corrections.
"""
from typing import Dict, List, Any, Optional
import json


class MedicalDataPostProcessor:
    """Post-processes VLM-extracted medical data to ensure quality and consistency."""
    
    @staticmethod
    def clean_extracted_data(
        extracted_data: Dict[str, Any],
        structure_type: str = None,
        strict_validation: bool = True
    ) -> Dict[str, Any]:
        """
        Clean and validate extracted medical data.
        
        Args:
            extracted_data: Raw extracted data from VLM
            structure_type: Report structure type for context-aware processing (optional)
            strict_validation: If True, remove incomplete entries
        
        Returns:
            Cleaned data with invalid entries removed
        """
        
        cleaned = {
            "patient_name": MedicalDataPostProcessor._clean_patient_name(extracted_data.get("patient_name", "")),
            "patient_age": MedicalDataPostProcessor._clean_age(extracted_data.get("patient_age", "")),
            "patient_gender": MedicalDataPostProcessor._clean_gender(extracted_data.get("patient_gender", "")),
            "report_date": MedicalDataPostProcessor._clean_date(extracted_data.get("report_date", "")),
            "report_name": extracted_data.get("report_name", ""),
            "report_type": extracted_data.get("report_type", ""),
            "doctor_names": extracted_data.get("doctor_names", ""),
            "medical_data": []
        }
        
        # Clean medical data entries
        raw_medical_data = extracted_data.get("medical_data", [])
        
        for entry in raw_medical_data:
            cleaned_entry = MedicalDataPostProcessor._clean_medical_entry(
                entry,

                strict_validation=strict_validation
            )
            
            if cleaned_entry:  # Only add if it passes validation
                cleaned["medical_data"].append(cleaned_entry)
        
        cleaned["total_fields_in_image"] = len(cleaned["medical_data"])
        
        return cleaned
    
    @staticmethod
    def standardize_field_names(medical_data: List[Dict[str, Any]], learned_synonyms: Dict[str, str] = None) -> List[Dict[str, Any]]:
        """
        Standardize field names using learned synonyms.
        Maps all variations to standard names for consistent filtering/timeline.
        
        Args:
            medical_data: List of medical data entries
            learned_synonyms: Dict mapping lowercase variations to standard names
                             E.g., {"haemoglobin": "Haemoglobin", "hemoglobin": "Haemoglobin"}
        
        Returns:
            Updated medical data with standardized field_names
        """
        
        if not learned_synonyms:
            learned_synonyms = {}
        
        for entry in medical_data:
            original_name = entry.get("field_name", "").strip()
            
            if original_name:
                # Look up standard name (case-insensitive)
                standard_name = learned_synonyms.get(original_name.lower(), original_name)
                
                # Update with standard name
                entry["field_name"] = standard_name
        
        return medical_data
    
    @staticmethod
    def _clean_medical_entry(
        entry: Dict[str, Any],
        strict_validation: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Clean a single medical data entry.
        Returns None if entry fails validation (incomplete data).
        """
        
        field_name = str(entry.get("field_name", "")).strip()
        field_value = str(entry.get("field_value", "")).strip()
        field_unit = str(entry.get("field_unit", "")).strip()
        normal_range = str(entry.get("normal_range", "")).strip()
        category = str(entry.get("category", "")).strip()
        notes = str(entry.get("notes", "")).strip()
        
        # CRITICAL: Skip entries with empty field_name or field_value
        if not field_name or not field_value:
            return None
        
        # Skip entries that are clearly malformed (e.g., field_value is a unit)
        if MedicalDataPostProcessor._is_value_malformed(field_value, field_unit, normal_range):
            return None
        
        # normal_range can be empty - that's OK
        # field_unit can be empty - that's OK
        # category and notes can be empty - that's OK
        
        cleaned_entry = {
            "field_name": field_name,
            "field_value": field_value,
            "field_unit": field_unit if field_unit else "",
            "normal_range": normal_range if normal_range else "",
            "category": category if category else "",
            "notes": notes if notes else "",
            "is_normal": None  # Will be calculated later
        }
        
        return cleaned_entry
    
    @staticmethod
    def _is_value_malformed(
        field_value: str,
        field_unit: str,
        normal_range: str
    ) -> bool:
        """
        Check if a field_value looks malformed.
        
        Malformed patterns:
        - value looks like a unit (%, /uL, /dL, etc)
        - value looks like a range ((x-y), [x-y])
        - value is clearly a range
        """
        
        if not field_value:
            return True
        
        lower_value = field_value.lower()
        
        # Check if value looks like a unit
        unit_patterns = ["%", "/ul", "/dl", "/l", "k/ul", "cells/l", "g/dl", "mg/dl", 
                        "iu/l", "mm/h", "μl", "mmol/l"]
        for pattern in unit_patterns:
            if pattern in lower_value:
                return True
        
        # Check if value looks like a range
        if "(" in field_value and ")" in field_value:  # (x-y) pattern
            return True
        if "[" in field_value and "]" in field_value:  # [x-y] pattern
            return True
        if " - " in field_value and not any(c.isalpha() for c in field_value):  # x - y pattern (numbers only)
            return True
        
        return False
    
    @staticmethod
    def _clean_patient_name(name: str) -> str:
        """Clean patient name."""
        if not name:
            return ""
        
        name = str(name).strip()
        
        # Remove common titles
        titles = ["dr.", "dr", "prof.", "prof", "د.", "دكتور", "أ.د", "الدكتور", 
                 "أستاذ", "البروفيسور", "mr.", "mr", "mrs.", "mrs", "ms.", "ms"]
        
        for title in titles:
            if name.lower().startswith(title):
                name = name[len(title):].strip()
                break
        
        # Must be at least 3 characters and look like a name (not a facility)
        if len(name) < 3:
            return ""
        
        # Exclude facility names
        facilities = ["clinic", "hospital", "lab", "laboratory", "phc", "center", "centre", 
                     "مختبر", "مرفق", "مستشفى", "عيادة", "جهاز"]
        
        if any(facility in name.lower() for facility in facilities):
            return ""
        
        return name
    
    @staticmethod
    def _clean_age(age: str) -> str:
        """Clean and validate age."""
        if not age:
            return ""
        
        age_str = str(age).strip()
        
        # Try to extract numeric age
        numeric_age = ''.join(c for c in age_str if c.isdigit())
        
        if numeric_age:
            age_num = int(numeric_age)
            # Validate age is within reasonable bounds (1-150)
            if 1 <= age_num <= 150:
                return numeric_age
        
        return ""
    
    @staticmethod
    def _clean_gender(gender: str) -> str:
        """Clean and normalize gender to Male/Female."""
        if not gender:
            return ""
        
        gender_str = str(gender).strip().lower()
        
        # Male variations
        if gender_str in ['male', 'm', 'ذكر', 'ذكر ', ' ذكر']:
            return 'Male'
        
        # Female variations
        elif gender_str in ['female', 'f', 'أنثى', 'انثى', 'أنثي', 'انثي']:
            return 'Female'
        
        # Already normalized
        elif gender_str in ['male', 'female']:
            return gender_str.capitalize()
        
        return ""
    
    @staticmethod
    def _clean_date(date_str: str) -> str:
        """Clean and normalize date to YYYY-MM-DD format."""
        if not date_str:
            return ""
        
        date_str = str(date_str).strip()
        
        # If already in YYYY-MM-DD format, return it
        if len(date_str) == 10 and date_str[4] == '-' and date_str[7] == '-':
            return date_str
        
        # Try to extract date components
        import re
        
        # Pattern: DD/MM/YYYY or DD-MM-YYYY or YYYY-MM-DD
        patterns = [
            (r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', 'ymd'),  # YYYY-MM-DD
            (r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', 'dmy'),  # DD-MM-YYYY
        ]
        
        for pattern, format_type in patterns:
            match = re.search(pattern, date_str)
            if match:
                if format_type == 'ymd':
                    year, month, day = match.groups()
                else:  # dmy
                    day, month, year = match.groups()
                
                # Validate
                try:
                    year = int(year)
                    month = int(month)
                    day = int(day)
                    
                    if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                        return f"{year:04d}-{month:02d}-{day:02d}"
                except:
                    pass
        
        return ""
    
    @staticmethod
    def calculate_is_normal(
        field_value: str,
        normal_range: str,
        field_unit: str = ""
    ) -> Optional[bool]:
        """
        Calculate if a value is within normal range.
        
        Returns:
            True if normal, False if abnormal, None if cannot determine
        """
        
        if not field_value or not normal_range:
            return None
        
        try:
            # Extract numeric value from field_value (handles operators like <, >, <=, >=)
            value_str = field_value.strip()
            
            # Extract numeric part
            import re
            numeric_match = re.search(r'[<>=]*\s*([\d.]+)', value_str)
            if not numeric_match:
                return None
            
            value = float(numeric_match.group(1))
            operator = re.search(r'([<>=]+)', value_str)
            
            # Parse normal range
            # Patterns: "10-15", "(10-15)", "10 - 15", "10 to 15"
            range_match = re.search(r'(\d+\.?\d*)\s*[-to]+\s*(\d+\.?\d*)', normal_range, re.IGNORECASE)
            
            if range_match:
                min_val = float(range_match.group(1))
                max_val = float(range_match.group(2))
                
                # If operator present (< > <= >=), use it
                if operator:
                    op = operator.group(1)
                    if op == '<' or op == '<=':
                        return value < min_val or (op == '<=' and value <= min_val)
                    elif op == '>' or op == '>=':
                        return value > max_val or (op == '>=' and value >= max_val)
                
                # Otherwise check if in range
                return min_val <= value <= max_val
            
            return None
        
        except Exception as e:
            print(f"⚠️ Error calculating is_normal for value={field_value}, range={normal_range}: {e}")
            return None
    
    @staticmethod
    def add_is_normal_to_entries(medical_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Calculate is_normal for all entries."""
        
        for entry in medical_data:
            entry['is_normal'] = MedicalDataPostProcessor.calculate_is_normal(
                entry.get('field_value', ''),
                entry.get('normal_range', ''),
                entry.get('field_unit', '')
            )
        
        return medical_data
    
    @staticmethod
    def validate_extraction_quality(
        extracted_data: Dict[str, Any],
        minimum_fields: int = 5
    ) -> Dict[str, Any]:
        """
        Validate overall extraction quality.
        
        Returns:
            Quality report with issues and recommendations
        """
        
        quality_report = {
            "total_fields_extracted": len(extracted_data.get("medical_data", [])),
            "has_patient_name": bool(extracted_data.get("patient_name")),
            "has_report_date": bool(extracted_data.get("report_date")),
            "has_doctor_info": bool(extracted_data.get("doctor_names")),
            "meets_minimum_threshold": len(extracted_data.get("medical_data", [])) >= minimum_fields,
            "issues": [],
            "warnings": []
        }
        
        # Check for issues
        if not quality_report["has_patient_name"]:
            quality_report["issues"].append("Missing patient name")
        
        if not quality_report["has_report_date"]:
            quality_report["issues"].append("Missing report date")
        
        if not quality_report["meets_minimum_threshold"]:
            quality_report["issues"].append(
                f"Only {quality_report['total_fields_extracted']} fields extracted "
                f"(minimum: {minimum_fields})"
            )
        
        # Check for warnings
        if not quality_report["has_doctor_info"]:
            quality_report["warnings"].append("Doctor information not found")
        
        # Check for missing ranges
        entries_without_ranges = sum(
            1 for entry in extracted_data.get("medical_data", [])
            if not entry.get("normal_range")
        )
        
        if entries_without_ranges > 0:
            quality_report["warnings"].append(
                f"{entries_without_ranges} fields missing normal ranges (OK per requirements)"
            )
        
        return quality_report
