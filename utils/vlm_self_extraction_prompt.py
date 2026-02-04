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
    """
    
    return f"""Extract ALL medical tests from this Arabic medical report (page {idx}/{total_pages}).

===== STEP 1: HEADER EXTRACTION =====
The header is a TWO-COLUMN table at the top.

RIGHT SIDE OF HEADER (look for these Arabic labels):
- اسم المريض = Patient Name → copy the Arabic name next to it to patient_name
- الجنس = Gender → أنثى = Female, ذكر = Male
- تاريخ الميلاد = Date of Birth → calculate age from this date

LEFT SIDE OF HEADER (look for these Arabic labels):
- تاريخ الطلب = Request Date → use as report_date (format: YYYY-MM-DD)
- الطبيب = Doctor → copy the Arabic name next to it to doctor_names

HEADER EXAMPLE from this image:
- اسم المريض: رئيسة خضر طالب خطيب ← this is patient_name
- الجنس: أنثى ← this means Female
- تاريخ الميلاد: 01/05/1975 ← calculate age: 2025 - 1975 = 50 years
- الطبيب: جهاد العملة ← this is doctor_names

===== STEP 2: TABLE EXTRACTION =====
This is a CBC (Complete Blood Count) report. The table is RTL (right-to-left).

TABLE COLUMNS (from RIGHT to LEFT):
1. الفحص (Test Name) - RIGHTMOST column, contains English test names
2. النتيجة (Result Value) - the numeric value
3. النتيجة الطبيعية (Normal Range) - in parentheses like (12-16)
4. الوحدة (Unit) - like %, g/dL, fL, pg, K/uL, M/uL
5. ملاحظات (Notes) - LEFTMOST column, usually empty or has *

CRITICAL: READ EACH ROW HORIZONTALLY!
For each row, the test name on the RIGHT pairs with the value DIRECTLY to its LEFT.

Example rows from this CBC:
- Test: "Red blood cell distribution width..." | Value: 14.4 | Range: (-) | Unit: %
- Test: "Platelet Crit" | Value: 0.23 | Range: (-) | Unit: %
- Test: "Monocytes" | Value: 0.1 | Range: (-) | Unit: K/uL
- Test: "White blood cells" | Value: 7.1 | Range: (4.6-11) | Unit: cells/L
- Test: "Neutrophils Granulocyte" | Value: 4.1 | Range: (-) | Unit: K/uL
- Test: "Neutrophils granulocyte%" | Value: 57.8 | Range: (37.0-92.0) | Unit: %G
- Test: "Lymphocytes%" | Value: 41.1 | Range: (-) | Unit: %L
- Test: "Red blood cells (RBC)" | Value: 5.2 | Range: (4.1-5.5) | Unit: M/uL
- Test: "Haemoglobin (HGB)" | Value: 12.6 | Range: (12-16) | Unit: g/dL
- Test: "Hematocrit (HCT)" | Value: 40.2 | Range: (37-48) | Unit: %
- Test: "Mean cell volume (MCV)" | Value: 77.3 | Range: (80-100) | Unit: fL
- Test: "Mean cell haemoglobin (MCH)" | Value: 24.2 | Range: (27-31.2) | Unit: pg
- Test: "Mean cell haemoglobin concentration (MCHC)" | Value: 31.3 | Range: (31-35) | Unit: %
- Test: "Monocytes(%)" | Value: 1.1 | Range: (3-7) | Unit: %
- Test: "Red blood cell distribution width" | Value: (-) | Range: (11.5-14.5) | Unit: %
- Test: "Platelets Count" | Value: 257 | Range: (140-450) | Unit: K/uL
- Test: "Eosinophils(%)" | Value: (-) | Range: (1-3) | Unit: %
- Test: "Mean Platelet Volume(MPV)" | Value: 9 | Range: (-) | Unit: fL
- Test: "Lymphocytes" | Value: 2.9 | Range: (0.7-4.8) | Unit: K/UL
- Test: "Basophiles(%)" | Value: (-) | Range: (0-0.75) | Unit: %
- Test: "Platelet Distribution Width" | Value: 17.7 | Range: (-) | Unit: 10(GSD)

DO NOT MIX VALUES BETWEEN ROWS!
Each test name must have the value from THE SAME ROW.

===== OUTPUT FORMAT =====
Return ONLY valid JSON (no markdown, no extra text):
{{
    "patient_name": "رئيسة خضر طالب خطيب",
    "patient_age": "50",
    "patient_gender": "Female",
    "report_date": "2025-12-31",
    "report_name": "HEMATOLOGY - Complete Blood Count (CBC)",
    "report_type": "Complete Blood Count (CBC)",
    "doctor_names": "جهاد العملة",
    "total_fields_in_image": 20,
    "medical_data": [
        {{
            "field_name": "Use English test name from rightmost column",
            "field_value": "Value from same row",
            "field_unit": "Unit from same row",
            "normal_range": "Range from same row or empty",
            "category": "HEMATOLOGY",
            "notes": ""
        }}
    ]
}}

report_type options: {', '.join(report_types)}
"""
