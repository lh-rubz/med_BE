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
        
        # Clean report date first (needed for DOB to age calculation)
        cleaned_report_date = MedicalDataPostProcessor._clean_date(extracted_data.get("report_date", ""))
        
        # Clean age - may involve calculating from DOB
        cleaned_age = MedicalDataPostProcessor._clean_age(
            extracted_data.get("patient_age", ""),
            report_date=cleaned_report_date
        )
        
        cleaned = {
            "patient_name": MedicalDataPostProcessor._clean_patient_name(extracted_data.get("patient_name", "")),
            "patient_age": cleaned_age,
            "patient_gender": MedicalDataPostProcessor._clean_gender(extracted_data.get("patient_gender", "")),
            "report_date": cleaned_report_date,
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
        
        # Deduplicate entries (remove exact duplicates from multi-page extraction)
        cleaned["medical_data"] = MedicalDataPostProcessor._deduplicate_entries(
            cleaned["medical_data"]
        )
        
        cleaned["total_fields_in_image"] = len(cleaned["medical_data"])
        
        return cleaned
    
    @staticmethod
    def _deduplicate_entries(medical_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove duplicate entries (same field name + value combination).
        Common in multi-page RTL reports where rows get extracted twice.
        
        Args:
            medical_data: List of extracted medical data entries
        
        Returns:
            Deduplicated list (keeps first occurrence of each unique entry)
        """
        seen = {}  # Key: (field_name, field_value), Value: index
        unique_entries = []
        
        for entry in medical_data:
            field_name = entry.get("field_name", "").strip().lower()
            field_value = entry.get("field_value", "").strip()
            
            # Create unique key from field name and value
            entry_key = (field_name, field_value)
            
            # Only add if we haven't seen this exact combination before
            if entry_key not in seen and field_name and field_value:
                seen[entry_key] = len(unique_entries)
                unique_entries.append(entry)
        
        return unique_entries
    
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
        """
        Clean patient name.
        Remove titles and position words.
        Reject corrupted/nonsensical text.
        """
        if not name:
            return ""
        
        name = str(name).strip()
        
        # Check for corrupted text (symbols, parentheses mixed with words)
        # Indicators of corruption: random symbols, medical terms, parentheses
        corruption_indicators = [")", "(", "[", "]", "{", "}", "الطب", "مختبر", "مرفق", "مستشفى"]
        for indicator in corruption_indicators:
            if indicator in name:
                # This might be corrupted, need more careful check
                # Count how many normal word characters vs special chars
                normal_chars = sum(1 for c in name if c.isalnum() or c in ' ـ')
                special_chars = sum(1 for c in name if c in ')([]{}<>')
                if special_chars > 0 or "الطب" in name:
                    # Likely corrupted
                    return ""
        
        # Remove common titles
        titles = ["dr.", "dr", "prof.", "prof", "د.", "دكتور", "أ.د", "الدكتور", 
                 "أستاذ", "البروفيسور", "mr.", "mr", "mrs.", "mrs", "ms.", "ms",
                 "رئيسة", "رئيس", "مدير", "مسؤول", "مساعد", "معاون"]
        
        name_lower = name.lower()
        for title in titles:
            if name_lower.startswith(title):
                name = name[len(title):].strip()
                name_lower = name.lower()
        
        # Must be at least 3 characters and look like a name (not a facility)
        if len(name) < 3:
            return ""
        
        # Exclude facility names
        facilities = ["clinic", "hospital", "lab", "laboratory", "phc", "center", "centre", 
                     "مختبر", "مرفق", "مستشفى", "عيادة", "جهاز", "الطب", "دارة", "وزارة"]
        
        if any(facility in name_lower for facility in facilities):
            return ""
        
        # Check if name contains meaningful Arabic or English words
        # If mostly gibberish, reject it
        words = name.split()
        if len(words) == 0:
            return ""
        
        # Reject if contains too many unusual characters or patterns
        # Corrupted text often has garbled Unicode or unusual patterns
        has_corruption = False
        for word in words:
            # Check for patterns like "خـير" (corrupted text)
            if "ـ" in word and len(word) < 3:  # Short words with diacritics
                has_corruption = True
            # Check for words that are just punctuation
            if not any(c.isalnum() for c in word):
                has_corruption = True
        
        if has_corruption and len(words) <= 2:
            return ""
        
        return name
    
    @staticmethod
    def _clean_age(age: str, report_date: str = "") -> str:
        """
        Clean and validate age.
        If age is a date (DOB), calculate age from report_date.
        
        Args:
            age: Age or DOB string
            report_date: Report date to use for DOB calculation (YYYY-MM-DD format)
        
        Returns:
            Age as a number string
        """
        if not age:
            return ""
        
        age_str = str(age).strip()
        
        # First try to extract numeric age
        numeric_age = ''.join(c for c in age_str if c.isdigit())
        
        # If we have a 4-digit number that looks like a year, it might be a DOB
        if len(numeric_age) == 4:
            # Could be a year (DOB)
            try:
                year = int(numeric_age)
                if 1900 <= year <= 2100:
                    # Try to parse as DOB and calculate age
                    calculated_age = MedicalDataPostProcessor._calculate_age_from_dob(age_str, report_date)
                    if calculated_age:
                        return str(calculated_age)
            except:
                pass
        
        # If we have 6 or 8 digits, likely a DOB (DDMMYYYY or YYYYMMDD)
        if len(numeric_age) in [6, 8]:
            calculated_age = MedicalDataPostProcessor._calculate_age_from_dob(age_str, report_date)
            if calculated_age:
                return str(calculated_age)
        
        # Try regular numeric age
        if numeric_age and len(numeric_age) <= 3:
            try:
                age_num = int(numeric_age)
                # Validate age is within reasonable bounds (1-150)
                if 1 <= age_num <= 150:
                    return numeric_age
            except:
                pass
        
        return ""
    
    @staticmethod
    def _calculate_age_from_dob(dob_str: str, report_date_str: str = "") -> Optional[int]:
        """
        Calculate age from Date of Birth and report date.
        
        Args:
            dob_str: Date of birth string (various formats)
            report_date_str: Report date in YYYY-MM-DD format
        
        Returns:
            Calculated age in years, or None if cannot calculate
        """
        try:
            from datetime import datetime
            import re
            
            # Parse DOB
            dob_patterns = [
                (r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', 'ymd'),  # YYYY-MM-DD
                (r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', 'dmy'),  # DD-MM-YYYY
            ]
            
            dob_date = None
            for pattern, format_type in dob_patterns:
                match = re.search(pattern, dob_str)
                if match:
                    if format_type == 'ymd':
                        year, month, day = match.groups()
                    else:  # dmy
                        day, month, year = match.groups()
                    
                    try:
                        dob_date = datetime(int(year), int(month), int(day))
                        break
                    except:
                        pass
            
            if not dob_date:
                return None
            
            # Parse report date
            report_date = None
            if report_date_str:
                try:
                    report_date = datetime.strptime(report_date_str, "%Y-%m-%d")
                except:
                    pass
            
            # Use current date if no report date
            if not report_date:
                report_date = datetime.now()
            
            # Calculate age
            age = report_date.year - dob_date.year
            
            # Adjust if birthday hasn't occurred yet this year
            if (report_date.month, report_date.day) < (dob_date.month, dob_date.day):
                age -= 1
            
            # Validate age is reasonable
            if 0 <= age <= 150:
                return age
            
            return None
        except:
            return None
    
    
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
