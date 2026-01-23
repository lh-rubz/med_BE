"""Self-correction analysis and corrective prompt generation for VLM extraction."""

import json
from typing import Dict, List, Any


def analyze_extraction_issues(extracted_data: Dict[str, Any], original_image_context: str = "") -> Dict[str, Any]:
    """
    Analyze extracted data for common issues and generate a report of what went wrong.
    
    Returns: {
        'has_issues': bool,
        'issues': [
            {'type': 'issue_type', 'field': 'field_name', 'value': 'extracted_value', 'reason': 'why it's wrong'}
        ],
        'issue_summary': 'human readable summary'
    }
    """
    issues = []
    
    # Check personal info issues
    if 'patient_name' in extracted_data:
        name = str(extracted_data.get('patient_name', '')).strip()
        if not name:
            issues.append({
                'type': 'missing_critical_field',
                'field': 'patient_name',
                'value': name,
                'reason': 'Patient name is empty or missing - should have found it in header'
            })
        elif name.lower() in ['patient', 'name', 'n/a', 'unknown', '']:
            issues.append({
                'type': 'placeholder_value',
                'field': 'patient_name',
                'value': name,
                'reason': f'Patient name appears to be a placeholder or label ("{name}") instead of actual name'
            })
        elif len(name) < 3:
            issues.append({
                'type': 'too_short',
                'field': 'patient_name',
                'value': name,
                'reason': f'Patient name too short ("{name}") - likely incorrect extraction'
            })
    
    if 'doctor_names' in extracted_data:
        doctor = str(extracted_data.get('doctor_names', '')).strip()
        if not doctor:
            issues.append({
                'type': 'missing_critical_field',
                'field': 'doctor_names',
                'value': doctor,
                'reason': 'Doctor name is empty - should search header, signature blocks, and footer'
            })
        elif doctor.lower() in ['doctor', 'dr', 'physician', 'signature', '']:
            issues.append({
                'type': 'placeholder_value',
                'field': 'doctor_names',
                'value': doctor,
                'reason': f'Doctor field appears to be a label ("{doctor}") instead of actual name'
            })
        elif len(doctor) < 3:
            issues.append({
                'type': 'too_short',
                'field': 'doctor_names',
                'value': doctor,
                'reason': f'Doctor name too short ("{doctor}") - likely incorrect extraction'
            })
    
    # Check date issues
    if 'report_date' in extracted_data:
        date_val = str(extracted_data.get('report_date', '')).strip()
        if not date_val:
            issues.append({
                'type': 'missing_critical_field',
                'field': 'report_date',
                'value': date_val,
                'reason': 'Report date is empty - required field'
            })
        elif ' ' in date_val and ':' in date_val:
            issues.append({
                'type': 'timestamp_included',
                'field': 'report_date',
                'value': date_val,
                'reason': f'Report date includes timestamp ({date_val}) - should be YYYY-MM-DD only, no time'
            })
        elif not ('20' in date_val or '19' in date_val):
            issues.append({
                'type': 'invalid_date_format',
                'field': 'report_date',
                'value': date_val,
                'reason': f'Report date format incorrect ({date_val}) - should be YYYY-MM-DD'
            })
    
    # Check medical data issues
    if 'medical_data' in extracted_data and isinstance(extracted_data['medical_data'], list):
        for idx, item in enumerate(extracted_data['medical_data']):
            test_name = str(item.get('field_name', '')).strip()
            test_val = str(item.get('field_value', '')).strip()
            test_unit = str(item.get('field_unit', '')).strip()
            test_range = str(item.get('normal_range', '')).strip()
            
            if not test_name:
                issues.append({
                    'type': 'missing_test_name',
                    'field': f'medical_data[{idx}].field_name',
                    'value': test_name,
                    'reason': 'Test name is empty - each row must have a test name'
                })
            
            if not test_val:
                issues.append({
                    'type': 'missing_value',
                    'field': f'medical_data[{idx}].field_value',
                    'value': test_val,
                    'reason': 'Test value is empty - should not include rows with no value'
                })
            
            # Check for misalignment patterns
            if '%' in test_val and test_unit and test_unit not in ['%']:
                issues.append({
                    'type': 'value_unit_swap',
                    'field': f'medical_data[{idx}]',
                    'value': f"value='{test_val}' unit='{test_unit}'",
                    'reason': f'Value contains unit symbol (%) - possible column misalignment: {test_name}'
                })
            
            if test_val.startswith('(') and test_val.endswith(')') and not test_range:
                issues.append({
                    'type': 'range_as_value',
                    'field': f'medical_data[{idx}]',
                    'value': f"value='{test_val}'",
                    'reason': f'Value looks like a range (parenthesized) - column misalignment: {test_name}'
                })
            
            if test_unit and any(ch.isdigit() for ch in test_unit) and test_name:
                issues.append({
                    'type': 'value_in_unit',
                    'field': f'medical_data[{idx}].field_unit',
                    'value': f"unit='{test_unit}'",
                    'reason': f'Unit contains digits - value/unit swap for {test_name}: unit should not be "{test_unit}"'
                })
    
    has_issues = len(issues) > 0
    issue_summary = f"Found {len(issues)} issue(s)" if has_issues else "No major issues detected"
    
    return {
        'has_issues': has_issues,
        'issues': issues,
        'issue_summary': issue_summary,
        'issue_count': len(issues)
    }


def generate_corrective_prompt(extracted_data: Dict[str, Any], analysis: Dict[str, Any], idx: int, total_pages: int) -> str:
    """
    Generate a corrective prompt that highlights what went wrong and tells the model how to fix it.
    This prompt is used for a second extraction pass to correct errors.
    """
    issues_text = "\n".join([
        f"- {issue['type'].upper()}: {issue['reason']}"
        for issue in analysis.get('issues', [])[:10]  # Show first 10 issues
    ])
    
    return f"""You are correcting a PREVIOUS EXTRACTION ATTEMPT from this report image (page {idx}/{total_pages}).

CRITICAL: The previous extraction had these ERRORS that must be FIXED:

{issues_text}

YOUR TASK: Extract the SAME fields again, but CORRECTLY this time.

BEFORE RETURNING YOUR ANSWER, VALIDATE:
1) patient_name: Must be an actual person's name (not "patient", "name", or empty)
2) doctor_names: Must be an actual doctor's name (not "doctor", "physician", or empty) - search signature blocks!
3) report_date: Must be YYYY-MM-DD format ONLY (no timestamp like "10:00:02")
4) Medical test names: Must have actual values, not empty or symbols
5) Test values: Must be numbers, not unit symbols or ranges
6) Test units: Must be medical abbreviations (not numbers or values)
7) Test ranges: Must be in range format like (X-Y), not single numbers

IF PREVIOUS EXTRACTION HAD THESE SPECIFIC ERRORS:
- Empty patient name → Search RIGHT side (Arabic) AND LEFT side (English) of header
- Empty doctor name → Check signature blocks at BOTTOM of page, check for "Dr. [Name]" pattern
- Timestamp in date → Extract ONLY the date portion before any space/time
- Value looks like unit → Re-trace row boundaries, find the actual numeric value
- Unit contains digits → Re-read the unit column, value may have shifted

EXTRACT EVERYTHING AGAIN. Return EXACTLY the same JSON structure as before, but with CORRECTED values:

{{
  "patient_name": "",
  "patient_age": "",
  "patient_dob": "",
  "patient_gender": "",
  "report_date": "",
  "doctor_names": "",
  "medical_data": [
    {{
      "field_name": "",
      "field_value": "",
      "field_unit": "",
      "normal_range": "",
      "is_normal": null,
      "category": "",
      "notes": ""
    }}
  ]
}}
"""
