"""Post-extraction validation and cleaning to remove hallucinated/misaligned data."""

import re
from typing import Dict, List, Any


def validate_and_clean_extraction(extracted_data: Dict[str, Any], page_num: int = 0, total_pages: int = 0) -> Dict[str, Any]:
    """
    Validate and clean extracted medical data, removing:
    1. Rows with empty values marked by * or -
    2. Rows with misaligned ranges (range doesn't match test value)
    3. Hallucinated ranges not in typical medical ranges
    4. Symbol-only units
    5. Rows copied from adjacent rows (same value from above/below)
    
    Returns cleaned data with validation report.
    """
    cleaned_data = {
        'medical_data': [],
        'validation_report': {
            'total_items_input': 0,
            'items_removed_empty_value': 0,
            'items_removed_misaligned_range': 0,
            'items_removed_hallucinated_range': 0,
            'items_removed_symbol_unit': 0,
            'items_removed_copied_from_neighbor': 0,
            'items_kept': 0,
            'issues_found': []
        }
    }
    
    if not extracted_data.get('medical_data'):
        return cleaned_data
    
    medical_items = extracted_data['medical_data']
    cleaned_data['validation_report']['total_items_input'] = len(medical_items)
    
    previous_values = []  # Track last 3 values to detect copying from neighbors
    
    for idx, item in enumerate(medical_items):
        field_name = str(item.get('field_name', '')).strip()
        field_value = str(item.get('field_value', '')).strip()
        field_unit = str(item.get('field_unit', '')).strip()
        normal_range = str(item.get('normal_range', '')).strip()
        
        skip_reason = None
        
        # 1. Check for empty value indicators
        if not field_value or field_value in ['*', '-', '—', 'N/A', 'NA', 'n/a', 'null', 'none', '', '.', '..']:
            skip_reason = f"Empty value marker: '{field_value}'"
            cleaned_data['validation_report']['items_removed_empty_value'] += 1
        
        # 2. Check for symbol-only units
        elif field_unit in ['*', '-', '—', '**', '***', '.', '..', '(-)']:
            skip_reason = f"Symbol-only unit: '{field_unit}'"
            cleaned_data['validation_report']['items_removed_symbol_unit'] += 1
            # Keep the item but clean the unit
            item['field_unit'] = ''
        
        # 3. Check for hallucinated ranges (very common issue on page 2)
        elif normal_range and not _is_valid_range(normal_range, field_value, field_name):
            skip_reason = f"Suspicious/hallucinated range: '{normal_range}' for {field_name}={field_value}"
            cleaned_data['validation_report']['items_removed_hallucinated_range'] += 1
            # Log but keep the item with empty range
            item['normal_range'] = ''
            cleaned_data['validation_report']['issues_found'].append({
                'type': 'hallucinated_range',
                'test': field_name,
                'removed_range': normal_range,
                'value': field_value
            })
        
        # 4. Check if value is copied from neighbor row
        elif field_value and _is_value_from_neighbor(field_value, previous_values):
            skip_reason = f"Value appears copied from adjacent row: '{field_value}' was in previous 3 rows"
            cleaned_data['validation_report']['items_removed_copied_from_neighbor'] += 1
        
        if skip_reason:
            cleaned_data['validation_report']['issues_found'].append({
                'type': 'item_removed',
                'test': field_name,
                'reason': skip_reason
            })
        else:
            # Item is valid, keep it
            cleaned_data['medical_data'].append(item)
            cleaned_data['validation_report']['items_kept'] += 1
        
        # Track values for neighbor detection
        if field_value and field_value not in ['*', '-', '—']:
            previous_values.append(field_value)
            if len(previous_values) > 3:
                previous_values.pop(0)
    
    return cleaned_data


def _is_valid_range(normal_range: str, field_value: str, field_name: str) -> bool:
    """
    Check if a normal range is plausible for the given test and value.
    Returns False if range looks hallucinated.
    """
    
    # Extract numbers from range
    range_numbers = re.findall(r'[\d.]+', normal_range)
    if len(range_numbers) < 2:
        return False  # Invalid range format
    
    try:
        range_min = float(range_numbers[0])
        range_max = float(range_numbers[1])
    except (ValueError, IndexError):
        return False
    
    # Extract value number
    value_match = re.search(r'[\d.]+', field_value)
    if not value_match:
        return True  # Qualitative result, can't validate numerically
    
    try:
        value_num = float(value_match.group())
    except ValueError:
        return True
    
    # Check for obviously hallucinated ranges
    # Very tiny ranges with large values (e.g., (0-0.75) for 14.4)
    if range_max - range_min < 1 and value_num > range_max * 5:
        return False
    
    # Suspicious patterns for specific test types
    test_name_lower = field_name.lower()
    
    # Hematology tests ranges (very specific)
    if any(test in test_name_lower for test in ['rbc', 'wbc', 'hemoglobin', 'hgb', 'hematocrit', 'hct']):
        # RBC: (4-5.5), WBC: (4-11), Hemoglobin: (12-16)
        if range_max < 2 and range_min < 1 and value_num > 5:
            return False  # Range way too small
    
    # Percentage tests
    if '%' in field_name or field_name.endswith('%'):
        if range_max > 100 or range_min > 100:
            return False  # Invalid percentage range
    
    # Clinical chemistry tests
    if any(test in test_name_lower for test in ['glucose', 'creatinine', 'cholesterol', 'triglyceride']):
        # Glucose: 70-120, Creatinine: 0.6-1.2, Cholesterol: 0-300
        if range_max < 50 and value_num > range_max * 10:
            return False  # Range way too small
    
    return True


def _is_value_from_neighbor(value: str, previous_values: List[str]) -> bool:
    """Check if value appears in recent previous values (likely copied from neighbor row)."""
    if not previous_values or not value:
        return False
    
    value_num = None
    try:
        value_num = float(re.search(r'[\d.]+', value).group())
    except (ValueError, AttributeError):
        return False  # Not numeric, hard to determine
    
    # Check if exact value appears in previous results
    for prev_val in previous_values:
        try:
            prev_num = float(re.search(r'[\d.]+', prev_val).group())
            if abs(value_num - prev_num) < 0.001:  # Near-exact match
                return True
        except (ValueError, AttributeError):
            continue
    
    return False


def filter_empty_values(medical_data: List[Dict]) -> List[Dict]:
    """
    Filter out items with empty field_values.
    Skip rows that have no actual result.
    """
    empty_indicators = {
        '', ' ', '-', '--', '—', '*', '**', '***', '****',
        'n/a', 'na', 'n.a', 'nil', 'none', 'unknown', 'null', 'nul',
        'not available', '.', '..', '...', '(*)', '(-)', 'غير متوفر', 'غير موجود'
    }
    
    filtered = []
    removed_count = 0
    
    for item in medical_data:
        field_value = str(item.get('field_value', '')).strip().lower()
        
        if field_value in empty_indicators or not field_value:
            removed_count += 1
            continue
        
        # Keep this item
        filtered.append(item)
    
    print(f"🗑️ Filtered: {removed_count} items with empty values, {len(filtered)} items kept")
    return filtered


def clean_ranges(medical_data: List[Dict]) -> List[Dict]:
    """
    Clean and normalize normal_range field.
    Remove symbol-only ranges and suspicious ranges.
    """
    empty_range_indicators = {'-', '--', '—', '*', '(*)', '(-)', '.', '..', 'n/a', 'na', 'none', 'unknown'}
    
    for item in medical_data:
        normal_range = str(item.get('normal_range', '')).strip()
        
        # Remove symbol-only ranges
        if normal_range in empty_range_indicators:
            item['normal_range'] = ''
            continue
        
        # Check for invalid range format
        if normal_range and not _is_valid_range_format(normal_range):
            item['normal_range'] = ''
    
    return medical_data


def _is_valid_range_format(range_str: str) -> bool:
    """Check if range string is in valid medical format."""
    # Valid patterns: (X-Y), (X-Y) unit, (X.X-Y.Y), etc.
    if not range_str:
        return False
    
    # Must have at least 2 numbers separated by dash
    numbers = re.findall(r'[\d.]+', range_str)
    if len(numbers) < 2:
        return False
    
    # Check for dash separator
    if '-' not in range_str:
        return False
    
    return True


def normalize_units(medical_data: List[Dict]) -> List[Dict]:
    """
    Normalize unit fields, removing symbol-only or invalid units.
    """
    symbol_only_units = {'*', '-', '—', '**', '***', '****', '.', '..', '(-)'}
    
    for item in medical_data:
        field_unit = str(item.get('field_unit', '')).strip()
        
        if field_unit in symbol_only_units or not field_unit:
            item['field_unit'] = ''
    
    return medical_data


def validate_page_2_extraction(medical_data: List[Dict], page_num: int) -> Dict[str, Any]:
    """
    Specialized validation for page 2 which has the most issues.
    """
    if page_num != 2:
        return {'status': 'skip', 'reason': 'Not page 2'}
    
    report = {
        'status': 'validated',
        'page': page_num,
        'total_items': len(medical_data),
        'issues': [],
        'critical_checks': {
            'has_percentage_tests': False,
            'has_empty_values': False,
            'has_symbol_units': False,
            'has_misaligned_ranges': False
        }
    }
    
    percentage_count = 0
    
    for idx, item in enumerate(medical_data):
        field_name = str(item.get('field_name', '')).strip()
        field_value = str(item.get('field_value', '')).strip()
        field_unit = str(item.get('field_unit', '')).strip()
        normal_range = str(item.get('normal_range', '')).strip()
        
        # Check for percentage tests (VERY COMMON on page 2 of hematology)
        if '%' in field_name:
            report['critical_checks']['has_percentage_tests'] = True
            percentage_count += 1
            
            # Validate percentage test format
            if field_value and not re.search(r'[\d.]+', field_value):
                report['issues'].append({
                    'type': 'percentage_value_format',
                    'test': field_name,
                    'value': field_value,
                    'suggestion': 'Percentage tests should have numeric values like 57.8'
                })
        
        # Check for empty values
        if field_value in ['*', '-', '—', '']:
            report['critical_checks']['has_empty_values'] = True
            report['issues'].append({
                'type': 'empty_value_kept',
                'test': field_name,
                'value': field_value
            })
        
        # Check for symbol-only units
        if field_unit in ['*', '-', '—']:
            report['critical_checks']['has_symbol_units'] = True
            report['issues'].append({
                'type': 'symbol_unit',
                'test': field_name,
                'unit': field_unit
            })
        
        # Check for misaligned ranges
        if normal_range and field_value:
            if not _is_valid_range(normal_range, field_value, field_name):
                report['critical_checks']['has_misaligned_ranges'] = True
                report['issues'].append({
                    'type': 'suspicious_range',
                    'test': field_name,
                    'value': field_value,
                    'range': normal_range
                })
    
    report['percentage_tests_found'] = percentage_count
    return report
