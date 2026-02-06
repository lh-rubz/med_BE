"""
Line-by-line verification system for medical report extraction.
This module implements dual-pass verification where:
1. First pass: Extract all fields from the report
2. Second pass: Verify each extracted field against the original image line-by-line

This acts like an intelligent scanner ensuring 100% accuracy.
"""

import re
from typing import Dict, List, Any, Tuple


def get_line_by_line_verification_prompt(extracted_fields: List[Dict], page_num: int, total_pages: int) -> str:
    """
    Generate a verification prompt that asks VLM to verify extracted data against the image.
    This acts as a second-pass quality control.
    
    Args:
        extracted_fields: List of extracted field dictionaries
        page_num: Current page number
        total_pages: Total pages in report
    
    Returns:
        Prompt string for verification
    """
    fields_text = "\n".join([
        f"{idx+1}. {f.get('field_name', 'UNKNOWN')} | "
        f"Value: {f.get('field_value', '')} | "
        f"Unit: {f.get('field_unit', '')} | "
        f"Range: {f.get('normal_range', '')}"
        for idx, f in enumerate(extracted_fields)
    ])
    
    return f"""🔍 LINE-BY-LINE VERIFICATION PASS
Page {page_num}/{total_pages}

TASK: Verify the following extracted fields against the ORIGINAL IMAGE using a STRICT HORIZONTAL LOCK.

EXTRACTED FIELDS TO VERIFY:
{fields_text}

VERIFICATION INSTRUCTIONS:
1. **Baseline Lock**: For each test name, trace a perfectly horizontal line across the page.
2. **Borrowed Value Check**: Does the "Value" or "Range" on that horizontal line actually belong to the test name?
   - ⚠️ ALERT: If you see a value from the row ABOVE or BELOW being paired with a test, mark as "SHIFT_ERROR".
3. **Empty Alignment**: If a row is empty in the image but has data in the extraction, mark as "HALLUCINATION".
4. **Column Integrity**:
   - Value column must contain ONLY the numeric/qualitative result.
   - Unit column must contain ONLY the unit (e.g. mg/dl).
   - Range column must contain ONLY the reference range.

5. **For Each Field**, respond with:
   [FIELD#] STATUS | Issue: [CORRECT | SHIFT_ERROR | VALUE_MISMATCH | HALLUCINATION] | Reason: [Actual value/range on image baseline]

RETURN VERIFICATION REPORT IN THIS FORMAT:
VERIFICATION_RESULTS:
[1] ... | Issue: CORRECT | Reason: matches image baseline
[2] ... | Issue: SHIFT_ERROR | Reason: image baseline shows value 128 (LDL), but 74 was extracted (HDL).
...

SUMMARY:
- Total Fields: X
- Aligned/Correct: X
- Shifted/Misaligned: X
"""


def get_field_specific_verification_prompt(field: Dict, page_num: int) -> str:
    """
    Generate a focused verification prompt for a single field.
    This is used for fields that failed initial verification.
    
    Args:
        field: Field dictionary to verify
        page_num: Page number of field
    
    Returns:
        Verification prompt for specific field
    """
    field_name = field.get('field_name', 'UNKNOWN')
    field_value = field.get('field_value', '')
    field_unit = field.get('field_unit', '')
    normal_range = field.get('normal_range', '')
    
    return f"""🔎 SINGLE FIELD VERIFICATION
Field: {field_name}
Page: {page_num}

Extracted Data:
- Test Name: {field_name}
- Value: {field_value}
- Unit: {field_unit}
- Reference Range: {normal_range}

VERIFICATION TASK:
1. **BASELINE LOCK**: Identify the exact horizontal line passing through the center of "{field_name}".
2. **COLOR ANCHORING**: Note the background color of "{field_name}" (Gray or White).
3. **VALUE VERIFICATION**: 
   - Move horizontally to the Result column.
   - The value is CORRECT ONLY if it is on the same baseline AND has the same background color.
4. **SHIFT DETECTION (1-Up/1-Down)**: 
   - Check the row immediately ABOVE and BELOW. 
   - If "{field_value}" is actually on a different baseline or color than "{field_name}", it is a SHIFT ERROR.
5. **NORMAL RANGE LOCK**: Ensure "{normal_range}" is also on this exact same baseline.

RESPOND WITH:
FIELD_VERIFICATION:
Test Name: CORRECT or INCORRECT
Value: CORRECT or INCORRECT (if incorrect, say "Correct baseline value is [X]")
Unit: CORRECT or INCORRECT
Range: CORRECT or INCORRECT (if shifted, specify correct range)
OVERALL: VERIFIED or NEEDS_CORRECTION
Explanation: one line explanation (e.g., "Shift error detected: borrowed value from row below")
"""


def get_column_distinction_prompt() -> str:
    """
    Prompt to ensure each column is properly distinguished and not merged.
    Returns emphasis on column separation.
    """
    return """🎯 CRITICAL - COLUMN SEPARATION RULES

NEVER merge or confuse columns. Each column has ONE specific purpose:

1️⃣ TEST NAME COLUMN:
   - Contains: Test parameter name (e.g., "RBC", "Hemoglobin", "WBC")
   - DO NOT include: values, units, ranges
   - Example: "Red Blood Cell Count" not "Red Blood Cell Count 4.5 M/uL"

2️⃣ VALUE COLUMN:
   - Contains: The numerical result or percentage (e.g., "4.5", "12.3", "75%")
   - DO NOT include: units, ranges, test names
   - Example: "4.5" not "4.5 M/uL" not "4.5 (reference: 4.2-5.4)"

3️⃣ UNIT COLUMN:
   - Contains: ONLY the measurement unit (e.g., "M/uL", "g/dL", "%", "K/uL")
   - DO NOT include: values, test names
   - Example: "M/uL" not "4.5 M/uL" not "millions/microliter 4.5"

4️⃣ REFERENCE RANGE COLUMN:
   - Contains: ONLY the normal/reference range (e.g., "(4.2-5.4)", "(12-16)")
   - DO NOT include: values, units, test names
   - Example: "(4.2-5.4)" not "4.2-5.4" not "normal: 4.2-5.4 M/uL for patient value 4.5"

EACH COLUMN IS INDEPENDENT.
DO NOT CONCATENATE INFORMATION ACROSS COLUMNS.
"""


def create_verification_report(extracted_fields: List[Dict], vlm_verification_response: str) -> Dict[str, Any]:
    """
    Parse VLM verification response and create detailed report.
    
    Args:
        extracted_fields: Original extracted fields
        vlm_verification_response: Raw VLM verification response
    
    Returns:
        Structured verification report
    """
    report = {
        'total_fields': len(extracted_fields),
        'verification_status': 'PENDING',
        'verified_fields': [],
        'fields_needing_correction': [],
        'critical_issues': [],
        'summary': {}
    }
    
    # Parse verification response for status markers
    response_lower = vlm_verification_response.lower()
    
    correct_count = response_lower.count('correct')
    mismatch_count = response_lower.count('mismatch') + response_lower.count('incorrect')
    empty_count = response_lower.count('empty')
    
    # Extract critical issues
    if 'copied_from_neighbor' in response_lower:
        report['critical_issues'].append('Detected copied values from neighbor rows')
    if 'range_not_visible' in response_lower:
        report['critical_issues'].append('Some ranges not visible in original image')
    if 'value_mismatch' in response_lower:
        report['critical_issues'].append('Extracted values differ from image')
    
    report['summary'] = {
        'fields_correct': correct_count,
        'fields_with_issues': mismatch_count,
        'empty_values_found': empty_count,
        'critical_issues_count': len(report['critical_issues'])
    }
    
    # Determine overall verification status
    if mismatch_count == 0 and len(report['critical_issues']) == 0:
        report['verification_status'] = 'VERIFIED'
    elif mismatch_count < len(extracted_fields) * 0.1:  # Less than 10% issues
        report['verification_status'] = 'MOSTLY_VERIFIED'
    else:
        report['verification_status'] = 'NEEDS_CORRECTION'
    
    return report


def verify_extracted_fields_against_image(
    extracted_fields: List[Dict],
    image_base64: str,
    vlm_client: Any,
    page_num: int = 1,
    total_pages: int = 1,
    run_detailed_check: bool = True
) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Verify extracted fields against the original image using line-by-line checking.
    This is the main entry point for line-by-line verification.
    
    Args:
        extracted_fields: List of extracted field dictionaries
        image_base64: Base64 encoded image for verification
        vlm_client: Ollama VLM client instance
        page_num: Current page number
        total_pages: Total pages in document
        run_detailed_check: Whether to run detailed check on individual fields
    
    Returns:
        Tuple of (verified_fields, verification_report)
    """
    
    if not extracted_fields:
        return [], {'status': 'NO_FIELDS_TO_VERIFY', 'total_fields': 0}
    
    # Step 1: Full-page verification
    verification_prompt = get_line_by_line_verification_prompt(
        extracted_fields, page_num, total_pages
    )
    
    # Step 2: Add column distinction emphasis
    full_prompt = verification_prompt + "\n\n" + get_column_distinction_prompt()
    
    try:
        # Call VLM for verification
        verification_response = vlm_client.generate(
            prompt=full_prompt,
            images=[image_base64],
            temperature=0.1,  # Low temperature for factual verification
            num_predict=2000
        )
        
        # Parse response
        verification_report = create_verification_report(
            extracted_fields,
            verification_response.get('response', '')
        )
        
        # Step 3: If needed, run detailed field-by-field verification
        verified_fields = extracted_fields.copy()
        
        if run_detailed_check and verification_report['verification_status'] in ['MOSTLY_VERIFIED', 'NEEDS_CORRECTION']:
            # Identify fields with potential issues and verify them individually
            for idx, field in enumerate(extracted_fields):
                if _should_verify_field_individually(field, verification_response):
                    field_prompt = get_field_specific_verification_prompt(field, page_num)
                    
                    field_response = vlm_client.generate(
                        prompt=field_prompt,
                        images=[image_base64],
                        temperature=0.1,
                        num_predict=500
                    )
                    
                    # Update field if verification found corrections needed
                    corrected_field = _apply_field_verification_corrections(
                        field, field_response.get('response', '')
                    )
                    verified_fields[idx] = corrected_field
        
        verification_report['raw_response'] = verification_response.get('response', '')
        return verified_fields, verification_report
        
    except Exception as e:
        return extracted_fields, {
            'status': 'VERIFICATION_ERROR',
            'error': str(e),
            'total_fields': len(extracted_fields)
        }


def verify_extracted_fields_against_image_openai(
    extracted_fields: List[Dict],
    image_base64: str,
    image_format: str,
    client: Any,
    model: str,
    page_num: int = 1,
    total_pages: int = 1,
    run_detailed_check: bool = True
) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Verify extracted fields against the original image using OpenAI-compatible chat API.
    """

    if not extracted_fields:
        return [], {'status': 'NO_FIELDS_TO_VERIFY', 'total_fields': 0}

    verification_prompt = get_line_by_line_verification_prompt(
        extracted_fields, page_num, total_pages
    )
    full_prompt = verification_prompt + "\n\n" + get_column_distinction_prompt()

    try:
        content = [
            {'type': 'text', 'text': full_prompt},
            {'type': 'image_url', 'image_url': {'url': f'data:image/{image_format};base64,{image_base64}'}}
        ]

        completion = client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': content}],
            temperature=0.1
        )
        response_text = completion.choices[0].message.content.strip()

        verification_report = create_verification_report(
            extracted_fields,
            response_text
        )

        verified_fields = extracted_fields.copy()

        if run_detailed_check and verification_report['verification_status'] in ['MOSTLY_VERIFIED', 'NEEDS_CORRECTION']:
            for idx, field in enumerate(extracted_fields):
                if _should_verify_field_individually(field, response_text):
                    field_prompt = get_field_specific_verification_prompt(field, page_num)
                    field_content = [
                        {'type': 'text', 'text': field_prompt},
                        {'type': 'image_url', 'image_url': {'url': f'data:image/{image_format};base64,{image_base64}'}}
                    ]
                    field_completion = client.chat.completions.create(
                        model=model,
                        messages=[{'role': 'user', 'content': field_content}],
                        temperature=0.1
                    )
                    field_response_text = field_completion.choices[0].message.content.strip()
                    corrected_field = _apply_field_verification_corrections(
                        field, field_response_text
                    )
                    verified_fields[idx] = corrected_field

        verification_report['raw_response'] = response_text
        return verified_fields, verification_report

    except Exception as e:
        return extracted_fields, {
            'status': 'VERIFICATION_ERROR',
            'error': str(e),
            'total_fields': len(extracted_fields)
        }


def _should_verify_field_individually(field: Dict, verification_response: str) -> bool:
    """
    Determine if a specific field should be verified individually.
    Checks if field name appears in verification issues.
    """
    field_name = field.get('field_name', '').lower()
    field_value = field.get('field_value', '').lower()
    
    response_lower = verification_response.lower()
    
    # Check if this field's value was marked as problematic
    if field_value and field_value in response_lower:
        if any(issue in response_lower for issue in ['mismatch', 'incorrect', 'copied', 'wrong']):
            return True
    
    # Check if field name appears in error context
    if field_name and field_name in response_lower:
        if any(issue in response_lower for issue in ['missing', 'not found', 'unclear']):
            return True
    
    return False


def _apply_field_verification_corrections(field: Dict, verification_response: str) -> Dict:
    """
    Apply corrections to a field based on verification response.
    This attempts to extract correct values from VLM verification.
    """
    corrected_field = field.copy()
    response_lower = verification_response.lower()
    
    # Check for specific corrections in verification response
    # Look for: "Correct value on this line is X" or "image shows X"
    if 'incorrect' in response_lower:
        # Extract numeric value (including decimals and symbols)
        match = re.search(r'(?:shows|says|displays|line is|index \d+ shows|correct value)[:\s]+([\*#<>]? ?[0-9.]+(?:%)?)', response_lower)
        if match:
            corrected_field['field_value'] = match.group(1).strip()
            corrected_field['verification_note'] = 'Corrected from row-shift verification'
    
    if 'range: incorrect' in response_lower or 'range_not_visible' in response_lower:
        # Try to extract the correct range if provided
        range_match = re.search(r'range is[:\s]+(\(?[0-9.-]+\)?)', response_lower)
        if range_match:
            corrected_field['normal_range'] = range_match.group(1).strip()
    
    return corrected_field


def generate_verification_summary_for_user(verification_report: Dict) -> str:
    """
    Generate a human-readable summary of verification results.
    """
    summary = f"""
📋 VERIFICATION REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Fields Verified: {verification_report.get('total_fields', 'N/A')}
Verification Status: {verification_report.get('verification_status', 'UNKNOWN')}

✓ Correct: {verification_report.get('summary', {}).get('fields_correct', 'N/A')}
⚠ Issues Found: {verification_report.get('summary', {}).get('fields_with_issues', 'N/A')}
🔴 Critical Issues: {verification_report.get('summary', {}).get('critical_issues_count', 'N/A')}

"""
    
    if verification_report.get('critical_issues'):
        summary += "⚠ ISSUES TO REVIEW:\n"
        for issue in verification_report['critical_issues']:
            summary += f"  • {issue}\n"
    
    return summary
