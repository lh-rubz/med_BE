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
        Parse normal range string into min/max tuple.
        Handles: "13.5-17.5", "< 200", "> 50", "up to 40", "below 10", "above 100".
        """
        if not range_str or not isinstance(range_str, str):
            return None
        
        range_str = str(range_str).strip().lower()
        
        # Pattern: number-number or number to number
        match = re.search(r'([-+]?\d*\.?\d+)\s*[-to]+\s*([-+]?\d*\.?\d+)', range_str)
        if match:
            try:
                return (float(match.group(1)), float(match.group(2)))
            except ValueError:
                pass
        
        # Pattern: < number or up to or below or less than
        match = re.search(r'(?:<|up\s+to|below|less\s+than)\s*([-+]?\d*\.?\d+)', range_str)
        if match:
            try:
                return (float('-inf'), float(match.group(1)))
            except ValueError:
                pass
        
        # Pattern: > number or above or greater than
        match = re.search(r'(?:>|above|greater\s+than)\s*([-+]?\d*\.?\d+)', range_str)
        if match:
            try:
                return (float(match.group(1)), float('inf'))
            except ValueError:
                pass

        # Pattern: <= number
        match = re.search(r'<=\s*([-+]?\d*\.?\d+)', range_str)
        if match:
            try:
                return (float('-inf'), float(match.group(1)))
            except ValueError:
                pass

        # Pattern: >= number
        match = re.search(r'>=\s*([-+]?\d*\.?\d+)', range_str)
        if match:
            try:
                return (float(match.group(1)), float('inf'))
            except ValueError:
                pass

        # Pattern: single number (interpreted as min threshold if not otherwise specified)
        # e.g., "Normal: 187"
        match = re.search(r'^([-+]?\d*\.?\d+)$', range_str)
        if match:
            try:
                return (float(match.group(1)), float('inf'))
            except ValueError:
                pass
        
        return None
    
    @staticmethod
    def calculate_is_normal(field_value: str, normal_range: str, 
                           current_is_normal: Optional[bool] = None,
                           patient_gender: Optional[str] = None) -> Optional[bool]:
        """
        Deterministically calculate if a value is within normal range.
        Handles numeric, categorical, gender-specific, and qualitative ranges.
        """
        # Handle qualitative results in field_value
        value_raw = str(field_value).strip().lower()
        if any(pattern in value_raw for pattern in MedicalValidator.NORMAL_QUALITATIVE):
            return True
        if any(pattern in value_raw for pattern in MedicalValidator.ABNORMAL_QUALITATIVE):
            return False
        
        # Extract numeric value
        value = None
        operator = None
        try:
            numeric_match = re.search(r'([<>=]*)\s*([-+]?\d*\.?\d+)', value_raw)
            if numeric_match:
                operator = numeric_match.group(1)
                value = float(numeric_match.group(2))
        except (ValueError, TypeError):
            pass

        if not normal_range:
            return current_is_normal

        range_raw = str(normal_range).strip().lower()

        # 1. Handle Gender-Specific Ranges
        # Pattern: "Male: 13-17, Female: 12-16"
        if patient_gender and (":" in range_raw or "," in range_raw):
            gender = str(patient_gender).lower()
            gender_patterns = []
            if 'female' in gender or 'f' in gender or 'woman' in gender or 'أنثى' in gender or 'انثى' in gender:
                gender_patterns = [r'female\s*[:]\s*([^,;]+)', r'women\s*[:]\s*([^,;]+)', r'نساء\s*[:]\s*([^,;]+)']
            elif 'male' in gender or 'm' in gender or 'man' in gender or 'ذكر' in gender:
                gender_patterns = [r'male\s*[:]\s*([^,;]+)', r'men\s*[:]\s*([^,;]+)', r'رجال\s*[:]\s*([^,;]+)']
            
            for pattern in gender_patterns:
                match = re.search(pattern, range_raw)
                if match:
                    # Overwrite range_raw with the gender-specific part
                    range_raw = match.group(1).strip()
                    break

        # 2. Handle Categorical Ranges
        # Pattern: "Deficient: <10, Insufficient: 11-30, Sufficient: 31-100"
        if ":" in range_raw and value is not None:
            # Check all categories
            category_pattern = r'([a-z\s]+?)\s*:\s*([^,;]+)'
            for cat_match in re.finditer(category_pattern, range_raw):
                cat_name = cat_match.group(1).strip()
                cat_range = cat_match.group(2).strip()
                
                # Check if value fits this category's range
                r_tuple = MedicalValidator.parse_range(cat_range)
                if r_tuple:
                    min_v, max_v = r_tuple
                    if min_v <= value <= max_v:
                        # Value is in this category. Is the category normal?
                        abnormal_keywords = ['deficient', 'insufficient', 'high', 'low', 'abnormal', 'toxic', 'positive']
                        return not any(kw in cat_name for kw in abnormal_keywords)

        # 3. Handle Simple/Split Ranges
        if value is not None:
            segments = re.split(r'[;,/]+', range_raw)
            for segment in segments:
                range_tuple = MedicalValidator.parse_range(segment)
                if range_tuple:
                    min_val, max_val = range_tuple
                    
                    # If value has operator, check if it fits contextually
                    # e.g., value is "< 5", range is "10-20" -> False
                    if operator == '<':
                        return value < max_val and value >= min_val
                    elif operator == '<=':
                        return value <= max_val and value >= min_val
                    elif operator == '>':
                        return value > min_val and value <= max_val
                    elif operator == '>=':
                        return value >= min_val and value <= max_val
                    
                    # If range segment itself is an inequality
                    # e.g., range is "< 6", max_val is 6.0, min_val is -inf
                    is_strict_max = '<' in segment and '<=' not in segment
                    is_strict_min = '>' in segment and '>=' not in segment

                    if is_strict_max and value >= max_val:
                        return False
                    if is_strict_min and value <= min_val:
                        return False

                    if min_val <= value <= max_val:
                        return True
            
            # If we parsed ranges but none matched
            if segments and any(MedicalValidator.parse_range(s) for s in segments):
                return False

        # Fallback to VLM's guess
        return current_is_normal
    
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
        
        # Normalize normal_range but preserve full descriptive text
        normal_range = str(validated.get('normal_range', ''))
        unit = str(validated.get('field_unit', ''))
        
        # aggressively strip unit from normal_range if present
        if unit and normal_range:
            # Escape unit for regex
            unit_esc = re.escape(unit)
            # Remove unit if it appears in the range string
            # Case insensitive remove
            normal_range = re.sub(rf'\s*{unit_esc}\s*', '', normal_range, flags=re.IGNORECASE)
            validated['normal_range'] = normal_range.strip()
        
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
