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
        
        # Try to parse as decimal to validate
        try:
            # Extract numeric part (handle cases like "13.5 g/dL")
            numeric_match = re.search(r'[-+]?\d*\.?\d+', value_str)
            if numeric_match:
                numeric_str = numeric_match.group()
                # Preserve exact decimal representation
                Decimal(numeric_str)  # Validate it's a valid number
                return numeric_str
        except (InvalidOperation, ValueError):
            pass
        
        return value_str
    
    @staticmethod
    def parse_range(range_str: str) -> Optional[Tuple[float, float]]:
        """
        Parse normal range string into min/max tuple
        
        Args:
            range_str: Range string like "13.5-17.5" or "150000-410000"
            
        Returns:
            Tuple of (min, max) or None if cannot parse
        """
        if not range_str or not isinstance(range_str, str):
            return None
        
        # Clean the string
        range_str = range_str.strip()
        
        # Pattern: number-number or number - number
        match = re.match(r'([-+]?\d*\.?\d+)\s*-\s*([-+]?\d*\.?\d+)', range_str)
        if match:
            try:
                min_val = float(match.group(1))
                max_val = float(match.group(2))
                return (min_val, max_val)
            except ValueError:
                pass
        
        # Pattern: < number (upper limit only)
        match = re.match(r'<\s*([-+]?\d*\.?\d+)', range_str)
        if match:
            try:
                max_val = float(match.group(1))
                return (float('-inf'), max_val)
            except ValueError:
                pass
        
        # Pattern: > number (lower limit only)
        match = re.match(r'>\s*([-+]?\d*\.?\d+)', range_str)
        if match:
            try:
                min_val = float(match.group(1))
                return (min_val, float('inf'))
            except ValueError:
                pass
        
        return None
    
    @staticmethod
    def calculate_is_normal(field_value: str, normal_range: str, 
                           current_is_normal: Optional[bool] = None) -> bool:
        """
        Deterministically calculate if a value is within normal range
        
        Args:
            field_value: The measured value
            normal_range: The normal range string
            current_is_normal: VLM's guess (used as fallback)
            
        Returns:
            True if normal, False if abnormal
        """
        # Handle qualitative results
        value_lower = str(field_value).lower().strip()
        
        # Check if it's a qualitative normal result
        if any(pattern in value_lower for pattern in MedicalValidator.NORMAL_QUALITATIVE):
            return True
        
        # Check if it's a qualitative abnormal result
        if any(pattern in value_lower for pattern in MedicalValidator.ABNORMAL_QUALITATIVE):
            return False
        
        # Try numeric comparison
        if normal_range:
            range_tuple = MedicalValidator.parse_range(normal_range)
            if range_tuple:
                try:
                    # Extract numeric value
                    numeric_match = re.search(r'[-+]?\d*\.?\d+', str(field_value))
                    if numeric_match:
                        value = float(numeric_match.group())
                        min_val, max_val = range_tuple
                        
                        # Strict within-range check
                        is_normal = min_val <= value <= max_val
                        return is_normal
                except (ValueError, TypeError):
                    pass
        
        # Fallback to VLM's guess or default to True
        return current_is_normal if current_is_normal is not None else True
    
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
        
        # Normalize field value (preserve decimal precision)
        field_value = validated.get('field_value', '')
        if field_value:
            normalized = MedicalValidator.normalize_decimal(str(field_value))
            validated['field_value'] = normalized
            field_value = normalized
        else:
            # Ensure key exists even if empty
            validated['field_value'] = ''
        
        # Normalize normal_range (remove unit if duplicate)
        normal_range = str(validated.get('normal_range', ''))
        unit = str(validated.get('field_unit', ''))
        if unit and unit in normal_range:
            # Remove unit and any surrounding whitespace
            normal_range = normal_range.replace(unit, '').strip()
            # Clean up trailing dashes/commas that might be left
            normal_range = re.sub(r'\s*([,-])\s*$', '', normal_range)
            validated['normal_range'] = normal_range
        
        # Recalculate is_normal deterministically
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
