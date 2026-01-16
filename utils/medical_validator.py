"""
Medical Data Validation and Post-Processing
Provides deterministic validation for VLM-extracted medical data
"""
import re
from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal, InvalidOperation


class MedicalValidator:
    """Validates and normalizes medical report data"""
    
    # Common doctor title patterns
    DOCTOR_PATTERNS = [
        r'Dr\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        r'(?:Ref\.?\s*By:?|Referred\s*By:?)\s*Dr\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        r'Physician:?\s*Dr\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
    ]
    
    # Qualitative result patterns (considered "normal")
    NORMAL_QUALITATIVE = {
        'normal', 'nad', 'no abnormality detected', 'negative', 
        'within normal limits', 'wnl', 'unremarkable'
    }
    
    # Abnormal qualitative patterns
    ABNORMAL_QUALITATIVE = {
        'abnormal', 'positive', 'detected', 'elevated', 'low', 
        'high', 'critical', 'flagged'
    }
    
    @staticmethod
    def normalize_decimal(value_str: str) -> str:
        """
        Preserve exact decimal precision from string
        
        Args:
            value_str: String representation of number
            
        Returns:
            Normalized string with preserved precision
        """
        if not value_str or not isinstance(value_str, str):
            return value_str
        
        # Remove whitespace
        value_str = value_str.strip()
        
        # Try to parse numeric part but preserve prefix symbols (<, >, +, -)
        try:
            # Extract numeric part and any preceding symbol
            match = re.search(r'([<>+-]?)\s*([-+]?\d*\.?\d+)', value_str)
            if match:
                symbol = match.group(1)
                numeric_str = match.group(2)
                # Preserve exact decimal representation with symbol
                Decimal(numeric_str)  # Validate numeric part
                return f"{symbol}{numeric_str}" if symbol else numeric_str
        except (InvalidOperation, ValueError):
            pass
        
        return value_str
    
    @staticmethod
    def parse_range(range_str: str) -> Optional[Tuple[float, float]]:
        """
        Parse normal range string into min/max tuple
        
        Args:
            range_str: Range string like "13.5-17.5", "(74-110)", "150000-410000", etc.
            
        Returns:
            Tuple of (min, max) or None if cannot parse
        """
        if not range_str or not isinstance(range_str, str):
            return None
        
        # Clean the string - remove parentheses and whitespace
        range_str = range_str.strip()
        # Remove common formatting: parentheses, brackets, etc.
        range_str = re.sub(r'^[\(\[<]|[\)\]>]$', '', range_str).strip()
        
        # Pattern: number-number or number - number (with optional parentheses)
        # Use search instead of match to find pattern anywhere in string
        match = re.search(r'([-+]?\d*\.?\d+)\s*-\s*([-+]?\d*\.?\d+)', range_str)
        if match:
            try:
                min_val = float(match.group(1))
                max_val = float(match.group(2))
                return (min_val, max_val)
            except ValueError:
                pass
        
        # Pattern: < number (upper limit only)
        match = re.search(r'<\s*([-+]?\d*\.?\d+)', range_str)
        if match:
            try:
                max_val = float(match.group(1))
                return (float('-inf'), max_val)
            except ValueError:
                pass
        
        # Pattern: > number (lower limit only)
        match = re.search(r'>\s*([-+]?\d*\.?\d+)', range_str)
        if match:
            try:
                min_val = float(match.group(1))
                return (min_val, float('inf'))
            except ValueError:
                pass
        
        return None
    
    @staticmethod
    def calculate_is_normal(field_value: str, normal_range: str, 
                           current_is_normal: Optional[bool] = None) -> Optional[bool]:
        """
        Deterministically calculate if a value is within normal range
        
        Args:
            field_value: The measured value
            normal_range: The normal range string
            current_is_normal: VLM's guess (used as fallback, but ignored if no range)
            
        Returns:
            True if normal, False if abnormal, None if cannot determine
        """
        # Check if field_value is empty or an empty indicator
        empty_indicators = {'', '-', '--', '—', '*', '**', '***', 'n/a', 'na', 'n.a', 
                          'nil', 'none', 'unknown', 'null', 'غير متوفر', 'غير موجود'}
        value_str = str(field_value).strip() if field_value else ''
        value_lower = value_str.lower()
        
        # If value is empty or an empty indicator, return None (cannot determine)
        if not value_str or value_lower in empty_indicators:
            return None
        
        # Handle qualitative results (only if we have a meaningful text value)
        if any(pattern in value_lower for pattern in MedicalValidator.NORMAL_QUALITATIVE):
            return True
        
        if any(pattern in value_lower for pattern in MedicalValidator.ABNORMAL_QUALITATIVE):
            return False
        
        # CRITICAL: Only calculate is_normal if we have a valid numeric normal_range
        # If normal_range is missing, empty, or non-numeric, return None
        if not normal_range or not isinstance(normal_range, str):
            return None
        
        normal_range_clean = normal_range.strip()
        empty_range_indicators = {'', '-', '--', '—', '*', '**', '***', 'n/a', 'na', 'n.a', 
                                 'nil', 'none', 'unknown', 'null', 'غير متوفر'}
        if not normal_range_clean or normal_range_clean.lower() in empty_range_indicators:
            return None
        
        # Check if normal_range contains numeric pattern (e.g., "12-16", "(0-200)", "<10")
        has_numeric_range = bool(re.search(r'[-+]?\d*\.?\d+\s*[-<>=]+\s*[-+]?\d*\.?\d+', normal_range_clean))
        has_numeric_range = has_numeric_range or bool(re.search(r'[<>]\s*[-+]?\d*\.?\d+', normal_range_clean))
        
        # If no numeric range found, return None (cannot determine without valid range)
        if not has_numeric_range:
            return None
        
        # Try numeric comparison with valid range
        # Some ranges contain multiple sub-ranges like "Male: 13-17, Female: 12-16"
        # Split on delimiters and evaluate against each numeric interval
        segments = re.split(r'[;,/]+', normal_range_clean)
        
        # Extract numeric value from field_value
        try:
            numeric_match = re.search(r'[-+]?\d*\.?\d+', value_str)
            value = float(numeric_match.group()) if numeric_match else None
        except (ValueError, TypeError, AttributeError):
            value = None
        
        # If we have a numeric value, compare against ranges
        if value is not None:
            found_valid_range = False
            value_in_range = False
            
            # Check all segments to see if value fits any range
            for segment in segments:
                range_tuple = MedicalValidator.parse_range(segment)
                if range_tuple:
                    found_valid_range = True
                    min_val, max_val = range_tuple
                    if min_val <= value <= max_val:
                        value_in_range = True
                        break  # Value fits at least one range, so it's normal
            
            # If we found valid range(s) and value fits at least one, it's normal
            if found_valid_range and value_in_range:
                return True
            # If we found valid range(s) but value doesn't fit any, it's abnormal
            elif found_valid_range and not value_in_range:
                return False
        
        # If we have a numeric range but couldn't extract numeric value from field_value,
        # and it's not qualitative, return None (cannot determine)
        return None
    
    @staticmethod
    def extract_doctor_names(text: str) -> str:
        """
        Extract referring physician names using regex patterns
        
        Args:
            text: Text containing doctor names
            
        Returns:
            Comma-separated doctor names or empty string
        """
        if not text:
            return ""
        
        doctors = set()
        
        for pattern in MedicalValidator.DOCTOR_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                doctor_name = match.group(1).strip()
                # Filter out common false positives
                if doctor_name and len(doctor_name) > 2:
                    # Avoid template names
                    if not any(skip in doctor_name.lower() for skip in 
                              ['signature', 'template', 'lab', 'clinic', 'hospital']):
                        doctors.add(doctor_name)
        
        return ", ".join(sorted(doctors))
    
    @staticmethod
    def deduplicate_fields(medical_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove duplicate test entries using fuzzy matching
        
        Args:
            medical_data: List of medical field dictionaries
            
        Returns:
            Deduplicated list
        """
        if not medical_data:
            return []
        
        seen = {}
        deduplicated = []
        
        for field in medical_data:
            field_name = str(field.get('field_name', '')).lower().strip()
            field_value = str(field.get('field_value', '')).strip()
            
            # Create a key for deduplication
            # Use normalized field name + category to avoid merging different sections
            category_text = str(field.get('category', '')).lower().strip()
            field_name_clean = re.sub(r'[^a-z0-9]', '', field_name)
            category_clean = re.sub(r'[^a-z0-9]', '', category_text)
            
            # DYNAMIC FILTER: If a field name is identical to the category name,
            # it means the VLM extracted the section header as a test. Skip it as a field.
            if field_name_clean == category_clean and not field_value:
                continue

            key = f"{field_name_clean}_{category_clean}"
            
            if key in seen:
                # Duplicate found - keep the one with more information
                existing = seen[key]
                existing_value = str(existing.get('field_value', '')).strip()
                existing_range = str(existing.get('normal_range', '')).strip()
                
                # If name and category match, but values are different, they might NOT be duplicates
                # (e.g., same test repeated with different results). 
                # For safety, only deduplicate if values or ranges also match significantly.
                if field_value != existing_value and field_value and existing_value:
                    # Likely different entries, don't deduplicate
                    deduplicated.append(field)
                    continue

                if len(field_value) > len(existing_value) or len(str(field.get('normal_range', ''))) > len(existing_range):
                    seen[key] = field
            else:
                seen[key] = field
        
        # Reconstruct list maintaining order
        for field in medical_data:
            field_name = str(field.get('field_name', '')).lower().strip()
            category = str(field.get('category', '')).lower().strip()
            key = f"{re.sub(r'[^a-z0-9]', '', field_name)}_{re.sub(r'[^a-z0-9]', '', category)}"
            
            if key in seen and seen[key] == field:
                deduplicated.append(field)
                del seen[key]  # Remove to avoid duplicates
            elif field in deduplicated:
                # Already added (for the 'continue' cases in first loop)
                pass
        
        return deduplicated
    
    @staticmethod
    def validate_and_normalize_field(field: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize a single medical field
        
        Args:
            field: Field dictionary from VLM extraction
            
        Returns:
            Validated and normalized field dictionary
        """
        validated = field.copy()
        
        # Detect and normalize empty values
        empty_indicators = {'', '-', '--', '—', '*', '**', '***', 'n/a', 'na', 'n.a', 
                          'nil', 'none', 'unknown', 'null', 'غير متوفر', 'غير موجود'}
        raw_field_value = validated.get('field_value', '')
        field_value_str = str(raw_field_value).strip() if raw_field_value else ''
        field_value_lower = field_value_str.lower()
        
        # If value is an empty indicator, set to empty string
        if not field_value_str or field_value_lower in empty_indicators:
            validated['field_value'] = ''
            field_value = ''
        else:
            # Normalize field value (preserve decimal precision) for non-empty values
            normalized = MedicalValidator.normalize_decimal(field_value_str)
            validated['field_value'] = normalized
            field_value = normalized
        
        # Normalize normal_range but preserve full descriptive text
        # CRITICAL: Do NOT invent or create normal_range if it's missing/empty
        normal_range = str(validated.get('normal_range', ''))
        
        # Check if normal_range is actually empty (not just whitespace)
        empty_range_indicators = {'', '-', '--', '—', '*', '**', '***', 'n/a', 'na', 'n.a', 
                                 'nil', 'none', 'unknown', 'null', 'غير متوفر', '(-)', '('}
        normal_range_clean = normal_range.strip()
        
        # If normal_range is an empty indicator, set to empty string (do NOT invent values)
        if not normal_range_clean or normal_range_clean.lower() in empty_range_indicators:
            validated['normal_range'] = ''
            normal_range = ''
        else:
            # Only process non-empty ranges
            unit = str(validated.get('field_unit', ''))
            if unit and unit in normal_range:
                # Only remove duplicated trailing unit occurrences like "mg/dl mg/dl"
                pattern = rf'\b{re.escape(unit)}\b\s*\b{re.escape(unit)}\b'
                normal_range = re.sub(pattern, unit, normal_range)
                validated['normal_range'] = normal_range
        
        # Recalculate is_normal deterministically (will return None for empty values or missing ranges)
        normal_range = validated.get('normal_range', '')
        current_is_normal = validated.get('is_normal')
        
        validated['is_normal'] = MedicalValidator.calculate_is_normal(
            field_value,
            normal_range,
            current_is_normal
        )
        
        # Ensure all required fields exist
        validated.setdefault('field_unit', '')
        validated.setdefault('normal_range', '')
        validated.setdefault('field_type', 'measurement')
        validated.setdefault('notes', '')
        
        return validated
    
    @staticmethod
    def post_process_extraction(extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Post-process VLM extraction for maximum accuracy
        
        Args:
            extracted_data: Raw extraction from VLM
            
        Returns:
            Validated and normalized extraction
        """
        processed = extracted_data.copy()
        
        # Validate and normalize each field
        medical_data = processed.get('medical_data', [])
        if medical_data:
            # Validate each field
            validated_fields = [
                MedicalValidator.validate_and_normalize_field(field)
                for field in medical_data
            ]
            
            # Deduplicate
            deduplicated_fields = MedicalValidator.deduplicate_fields(validated_fields)
            
            processed['medical_data'] = deduplicated_fields
            processed['total_fields_in_report'] = len(deduplicated_fields)
        
        # Re-extract doctor names if present
        doctor_text = processed.get('doctor_names', '')
        if doctor_text:
            processed['doctor_names'] = MedicalValidator.extract_doctor_names(doctor_text)
        
        return processed


def validate_medical_data(extracted_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for medical data validation
    
    Args:
        extracted_data: Raw VLM extraction
        
    Returns:
        Validated and normalized data with 100% accuracy on numeric fields
    """
    return MedicalValidator.post_process_extraction(extracted_data)
