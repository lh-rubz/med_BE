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
    
    return f"""Extract ALL medical tests from this report image (page {idx}/{total_pages}).

STEP 1: EXTRACT HEADER INFO FIRST
Look at the TOP section of the report (before the table).
Find these Arabic labels and extract the value NEXT TO each label:

| Arabic Label | English | What to Extract |
|-------------|---------|-----------------|
| اسم المريض | Patient Name | Full name next to this label |
| الجنس | Gender | أنثى=Female, ذكر=Male |
| تاريخ الميلاد | DOB | Date like 01/05/1975 |
| تاريخ الطلب | Report Date | Date like 2025-12-31 |
| الطبيب | Doctor | Doctor name next to this label |

IMPORTANT: 
- "اسم المريض" and "الطبيب" are DIFFERENT fields - don't confuse them!
- Patient name is at "اسم المريض:", Doctor name is at "الطبيب:"
- Calculate age: Report Year - Birth Year (e.g., 2025 - 1975 = 50)

STEP 2: EXTRACT TABLE DATA
The table has these columns (RIGHT to LEFT for Arabic headers):
| ملاحظات | الوحدة | النتيجة الطبيعية | النتيجة | الفحص |
| Notes | Unit | Normal Range | Value | Test Name |

For EACH row, read from RIGHT to LEFT:
1. Test Name (الفحص) - rightmost column
2. Value (النتيجة) - next column left
3. Normal Range (النتيجة الطبيعية) - next column left  
4. Unit (الوحدة) - next column left
5. Notes (ملاحظات) - leftmost column

CRITICAL: Stay on the SAME ROW. Each test name matches the value directly to its left.

Example from this report:
- Row: "Fasting Blood Sugar (FBS)" | 109 | (74-110) | mg/dl | 
- Extract: field_name="Fasting Blood Sugar (FBS)", field_value="109", normal_range="(74-110)", field_unit="mg/dl"

JSON OUTPUT (only JSON, no markdown):
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
            "field_name": "",
            "field_value": "",
            "field_unit": "",
            "normal_range": "",
            "category": "Clinical Chemistry",
            "notes": ""
        }}
    ]
}}

report_type options: {', '.join(report_types)}
"""
