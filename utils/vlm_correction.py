"""Self-correction analysis and corrective prompt generation for VLM extraction."""

import json
import re
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
        # Check for common wrong extractions (device names, facility names, etc.)
        elif any(keyword in name.lower() for keyword in ['device', 'جهاز', 'treatment', 'lab', 'clinic', 'hospital', 'facility', 'equipment']):
            issues.append({
                'type': 'wrong_extraction_type',
                'field': 'patient_name',
                'value': name,
                'reason': f'Extracted value appears to be a device/facility name ("{name}"), not a patient name. Search for actual person name in header.'
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
            
            # Check for symbol-only units (corruption indicator)
            if test_unit in ['*', '-', '--', '—']:
                issues.append({
                    'type': 'invalid_unit_symbol',
                    'field': f'medical_data[{idx}].field_unit',
                    'value': f"unit='{test_unit}'",
                    'reason': f'Unit is just a symbol ("{test_unit}") - {test_name} should have a proper medical unit'
                })
            
            # Check for unusual/wrong units
            if test_unit and not re.match(r'^[\w\/%\-\.]+$', test_unit):
                issues.append({
                    'type': 'invalid_unit_format',
                    'field': f'medical_data[{idx}].field_unit',
                    'value': f"unit='{test_unit}'",
                    'reason': f'Unit format looks wrong ("{test_unit}") for {test_name}'
                })
            
            # Check for value/range contradictions
            if test_val and test_range:
                try:
                    # Extract numeric value
                    val_match = re.search(r'[\d.]+', test_val)
                    range_matches = re.findall(r'[\d.]+', test_range)
                    
                    if val_match and len(range_matches) >= 2:
                        val_num = float(val_match.group())
                        range_min = float(range_matches[0])
                        range_max = float(range_matches[1])
                        
                        # Check if value is way outside range (suggests misalignment)
                        if val_num < range_min * 0.1 or val_num > range_max * 10:
                            issues.append({
                                'type': 'value_range_mismatch',
                                'field': f'medical_data[{idx}]',
                                'value': f"{test_name}: value={test_val}, range={test_range}",
                                'reason': f'Value {test_val} is extremely outside range {test_range} - likely misalignment'
                            })
                except:
                    pass
            
            # Check for misalignment patterns
            if '%' in test_val and test_unit and test_unit not in ['%']:
                issues.append({
                    'type': 'value_unit_swap',
                    'field': f'medical_data[{idx}]',
                    'value': f"value='{test_val}' unit='{test_unit}'",
                    'reason': f'Value contains % but unit is different - column misalignment: {test_name}'
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


def generate_prompt_enhancement_request(original_prompt: str, extracted_data: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    """
    Ask the model to enhance and personalize the extraction prompt based on what it saw in the report
    and what went wrong.
    """
    issues_text = "\n".join([
        f"- {issue['type']}: {issue['reason']}"
        for issue in analysis.get('issues', [])[:10]
    ])
    
    extracted_summary = json.dumps(extracted_data, indent=2, ensure_ascii=False)[:1000]
    
    return f"""You are a prompt engineering expert for medical report extraction.

TASK: Analyze the medical report image you just processed and enhance the extraction prompt to fix specific issues.

ORIGINAL PROMPT:
{'-'*60}
{original_prompt[:1500]}...
{'-'*60}

PREVIOUS EXTRACTION (had errors):
{extracted_summary}

ISSUES DETECTED:
{issues_text}

YOUR JOB:
1. Look at the actual report image layout, structure, and language
2. Identify WHERE exactly the correct information appears in THIS specific report
3. Enhance the original prompt by adding SPECIFIC INSTRUCTIONS for THIS report, including:
   - Exact locations where patient name appears (e.g., "top-right corner after 'اسم المريض:'")
   - Exact locations where doctor name appears (e.g., "bottom-left signature block", "footer after 'Dr.'")
   - Report language (Arabic/English/bilingual) and which side has which language
   - Specific table structure and column positions for medical data
   - Any unique formatting patterns in THIS report
4. Add specific corrections for each detected issue
5. Make the prompt PERSONALIZED for THIS specific report's layout and structure

Return a JSON object with:
{{
  "enhanced_prompt": "The complete enhanced extraction prompt with specific instructions for THIS report",
  "key_observations": [
    "observation 1 about this report's layout",
    "observation 2 about where patient name is located",
    "observation 3 about doctor signature location",
    "etc."
  ]
}}

Be specific about physical locations (top/bottom, left/right, header/footer, margins, signature blocks).
"""


def generate_corrective_prompt(extracted_data: Dict[str, Any], analysis: Dict[str, Any], 
                               idx: int, total_pages: int, enhanced_prompt: str = None,
                               original_prompt: str = None) -> str:
    """
    Generate a corrective prompt that highlights what went wrong and tells the model how to fix it.
    Uses enhanced prompt if available, otherwise uses default correction approach.
    """
    issues_text = "\n".join([
        f"- {issue['type'].upper()}: {issue['reason']}"
        for issue in analysis.get('issues', [])[:10]
    ])
    
    # If we have an enhanced prompt, use it with issue context
    if enhanced_prompt:
        return f"""You are re-extracting data from this medical report (page {idx}/{total_pages}) with ENHANCED INSTRUCTIONS.

CRITICAL: The previous extraction had these ERRORS:
{issues_text}

ENHANCED EXTRACTION INSTRUCTIONS (personalized for THIS report):
{'-'*60}
{enhanced_prompt}
{'-'*60}

FOLLOW THE ENHANCED INSTRUCTIONS CAREFULLY. They are specifically tailored to THIS report's layout and structure.

Extract the data again using the enhanced instructions. Return the complete JSON object with corrected values."""
    
    # Fallback to original correction approach
    return f"""You are correcting a PREVIOUS EXTRACTION ATTEMPT from this report image (page {idx}/{total_pages}).

CRITICAL: The previous extraction had these ERRORS that must be FIXED:

{issues_text}

YOUR TASK: Extract the SAME fields again, but CORRECTLY this time.

COMMON MISTAKES TO AVOID:
1) Patient name: Do NOT extract device names, facility names, or labels. Extract the PERSON'S actual name.
2) Doctor name: Search signature blocks, footer, header - extract the actual physician name, not a label.
3) Units: Do NOT use symbols like "*" or "-". Use proper medical abbreviations (mg/dl, g/dL, %, etc.).
4) Values: Check that values are reasonable for the test. If value is 10x smaller/larger than range, re-check alignment.
5) When value is outside range: Re-read that row carefully - you likely mixed columns from different rows.

BEFORE RETURNING YOUR ANSWER, VALIDATE:
1) patient_name: Must be an actual person's name (3+ chars), not a device/facility/label
2) doctor_names: Must be an actual doctor's name (3+ chars), not a label
3) report_date: Must be YYYY-MM-DD format ONLY (no timestamp)
4) Medical test units: Must be abbreviations like mg/dl, g/dL, %, fL, pg - NOT symbols or wrong codes
5) Medical test values: Must be realistic compared to normal range
6) If a value seems far outside its range, RECHECK that row - you may have mixed columns

EXTRACTION RULES:
- Only accept tests where field_name AND field_value are both non-empty
- Use correct medical units (never "*", "-", or random characters)
- If unsure about a unit, try to infer from the test name

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
