"""
Self-Prompting: Model analyzes report structure and writes its own extraction prompt.
This ensures compatibility with all report types without predefined structure patterns.
"""


def get_self_prompting_analysis_prompt(idx: int, total_pages: int) -> str:
    """
    Phase 1: Ask model to analyze the report and write its own extraction prompt.
    The model understands the structure better than hardcoded rules.
    """
    return f"""You are analyzing page {idx}/{total_pages} of a medical report.

STEP 1: ANALYZE THE REPORT STRUCTURE
Look at this medical report image and identify:
1. Layout direction: Is it LTR (left-to-right, English) or RTL (right-to-left, Arabic)?
2. Language: English, Arabic, or Bilingual?
3. Table structure: How many columns? What are the headers?
4. Column order: From left to right (or right to left if RTL), what columns are in what order?
5. Number of data rows: How many test entries do you see?

STEP 2: WRITE YOUR OWN EXTRACTION PROMPT
Based on what you see, write a detailed extraction prompt that YOU would use to extract data from this report accurately.
Your prompt should:
- Explain how to read the table (column by column, row by row)
- Specify what to extract for each column
- Include exact value preservation rules (operators, decimal places, etc.)
- Explain that empty fields should be returned as empty strings
- Specify JSON output format

STEP 3: RETURN THIS EXACT JSON (no markdown, no extra text):
{{
  "language": "English|Arabic|Bilingual",
  "direction": "LTR|RTL",
  "column_count": 3|4|5|6,
  "columns": ["col1_name", "col2_name", "col3_name", ...],
  "total_test_rows_estimate": <number>,
  "extraction_prompt": "YOUR DETAILED EXTRACTION PROMPT HERE - make it clear and specific for THIS report structure"
}}

Remember: Your extraction prompt will be used directly by the model to extract medical data. Make it clear, specific, and detailed.
Include exact instructions on:
- How to read the table (direction and order)
- What each column contains
- How to handle empty cells
- How to preserve exact values (operators, decimals, spacing)
- Expected JSON output format
"""


def get_self_directed_extraction_prompt(
    analysis_data: dict,
    idx: int,
    total_pages: int,
    report_types: list
) -> str:
    """
    Phase 2: Use the model's own analysis to guide extraction.
    The model's extraction_prompt tells it exactly how to read the report.
    """
    
    custom_extraction_prompt = analysis_data.get(
        'extraction_prompt',
        'Extract all medical test data from this report.'
    )
    
    report_metadata = f"""
REPORT METADATA TO EXTRACT (Page {idx}/{total_pages}):
- patient_name: Patient's name from header (remove titles: Dr., Mr., Mrs., etc.)
- patient_age: Age as number only
- patient_gender: Convert to "Male" or "Female" (or "" if not found)
- report_date: Date in YYYY-MM-DD format only (no time)
- report_name: The report section title (e.g., "HAEMATOLOGY", "BIOCHEMISTRY")
- report_type: Match to: {', '.join(report_types)}
- doctor_names: Referring doctor name (remove Dr. title)

DATA EXTRACTION RULES (Critical):
1. Take values EXACTLY as shown in the report
2. If a field is empty/blank in the report, return empty string ""
3. If normal_range is missing, that's OK - return ""
4. Preserve operators: If shows "< 5.7", keep it as "< 5.7"
5. Preserve decimals exactly: 14.5 not 14.50
6. Only include entries with BOTH field_name and field_value (skip empty rows)
7. Read each row independently - do NOT mix values from different rows

THE MODEL'S ANALYSIS OF THIS REPORT:
- Language: {analysis_data.get('language', 'Unknown')}
- Direction: {analysis_data.get('direction', 'Unknown')}
- Columns: {', '.join(analysis_data.get('columns', []))}
- Estimated rows: {analysis_data.get('total_test_rows_estimate', 'Unknown')}

THE MODEL'S EXTRACTION INSTRUCTIONS FOR THIS SPECIFIC REPORT:
{custom_extraction_prompt}

JSON OUTPUT FORMAT (exactly this structure):
{{
    "patient_name": "",
    "patient_age": "",
    "patient_gender": "",
    "report_date": "YYYY-MM-DD",
    "report_name": "",
    "report_type": "",
    "doctor_names": "",
    "total_fields_in_image": 0,
    "medical_data": [
        {{
            "field_name": "Test Name",
            "field_value": "123.4",
            "field_unit": "mg/dL",
            "normal_range": "100-200",
            "category": "SECTION NAME",
            "notes": ""
        }}
    ]
}}

VALIDATION:
- Count all rows: How many tests do you see? {analysis_data.get('total_test_rows_estimate', '?')} or more/less?
- Only return rows with field_name AND field_value
- If value is empty, skip that row
- If range is empty, that's OK - leave it empty
- Do NOT invent data

Return ONLY valid JSON (no markdown).
"""
    
    return report_metadata


def get_simplified_extraction_prompt(idx: int, total_pages: int, report_types: list) -> str:
    """
    Simplified one-shot extraction for LTR and RTL medical reports.
    Generic prompt that works on any report structure.
    """
    
    return f"""Extract ALL medical tests from this medical report image (page {idx}/{total_pages}).

===== STEP 1: DETECT REPORT LAYOUT =====
First, identify if this is:
- LTR (English): Read left-to-right
- RTL (Arabic): Read right-to-left, header often has two columns side by side

===== STEP 2: EXTRACT HEADER INFO =====
Look for these fields in the header area:

FOR ARABIC REPORTS (RTL - two column header):
The header typically has TWO separate boxes/columns side by side.
- RIGHT box contains: اسم المريض (Patient Name), الجنس (Gender), تاريخ الميلاد (DOB)
- LEFT box contains: تاريخ الطلب (Report Date), الطبيب (Doctor Name)

Extract:
- patient_name: Find "اسم المريض" label, copy the COMPLETE name (ALL words, do not skip any)
- patient_gender: Find "الجنس" → أنثى = Female, ذكر = Male
- patient_age: Find "تاريخ الميلاد" (DOB), calculate: current_year - birth_year
- report_date: Find "تاريخ الطلب", convert to YYYY-MM-DD format
- doctor_names: Find "الطبيب" label, copy the name

IMPORTANT: patient_name and doctor_names are DIFFERENT people in DIFFERENT boxes!

FOR ENGLISH REPORTS (LTR):
Look for labeled fields like "Patient Name:", "Gender:", "Date:", "Doctor:"

===== STEP 3: EXTRACT TABLE DATA =====
The main data table contains medical test results.

TABLE READING RULES:
1. First identify ALL column headers
2. For RTL tables: columns go RIGHT to LEFT (Test Name is usually rightmost)
3. For LTR tables: columns go LEFT to RIGHT (Test Name is usually leftmost)
4. Read ONE ROW at a time - stay on the same horizontal line
5. Each test name pairs ONLY with values in the SAME ROW

COMMON COLUMNS:
- Test Name (الفحص) - the name of the medical test (often in English)
- Result/Value (النتيجة) - the numeric result
- Normal Range (النتيجة الطبيعية) - reference range, often in parentheses
- Unit (الوحدة) - measurement unit (%, g/dL, mg/dL, fL, pg, K/uL, M/uL, etc.)
- Notes (ملاحظات) - flags or comments

CRITICAL EXTRACTION RULES:
1. Read test name from the Test column
2. Read value from the Value column IN THE SAME ROW
3. DO NOT mix values between different rows
4. If value cell is empty, has only "-" or "(-)", skip that row entirely
5. Extract test names EXACTLY as written (preserve English names)
6. Each test should appear only ONCE

===== OUTPUT FORMAT =====
Return ONLY valid JSON (no markdown, no code blocks, no extra text):
{{
    "patient_name": "Complete patient name as shown",
    "patient_age": "Calculated age as number",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD",
    "report_name": "Report section title",
    "report_type": "Match to one of the available types",
    "doctor_names": "Doctor name if found",
    "total_fields_in_image": 0,
    "medical_data": [
        {{
            "field_name": "Test name exactly as shown",
            "field_value": "Numeric value from SAME row",
            "field_unit": "Unit from SAME row",
            "normal_range": "Range from SAME row or empty string",
            "category": "Section name from report",
            "notes": ""
        }}
    ]
}}

report_type options: {', '.join(report_types)}
"""
