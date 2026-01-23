"""Self-prompting: Let the model create its own extraction prompt after analyzing the report."""

def get_report_analysis_prompt(idx, total_pages):
    """Ask the model to analyze the report and create a custom extraction prompt."""
    return f"""You are an expert medical report analyst. Look at this medical report image (page {idx}/{total_pages}).

YOUR TASK: Analyze this report and create a CUSTOM extraction prompt for it.

STEP 1 - ANALYZE THE REPORT:
1. What language(s) is it in? (Arabic, English, bilingual?)
2. How many rows are in the medical data table? COUNT them carefully.
3. What are the column headers? (Test name, Value, Unit, Normal Range, etc.)
4. Where is the patient information? (name, gender, age, date)
5. What is the table structure? (Which column has what?)
6. Are normal ranges in parentheses like (10-15) or another format?

STEP 2 - CREATE A CUSTOM EXTRACTION PROMPT:
Write detailed instructions on HOW to extract data from THIS specific report, including:
- Where exactly the patient name is located
- Where the gender field is (convert Arabic to English: ذكر->Male, أنثى->Female)
- The exact number of rows in the table
- Which column contains test names (column 1? column 4?)
- Which column contains values
- Which column contains units
- Which column contains normal ranges
- Any special formatting in this report

Return a JSON object:
{{
  "report_language": "Arabic/English/Bilingual",
  "total_test_rows": 25,
  "patient_info_location": "Top header section",
  "table_structure": "Column 1: Test names (right side), Column 2: Values, Column 3: Units, Column 4: Normal ranges",
  "gender_value_seen": "أنثى (means Female)",
  "special_notes": "Any unique observations",
  "extraction_instructions": "Detailed step-by-step instructions:
1. Patient name is in top-right after 'اسم المريض'
2. Gender is in the header table, convert 'أنثى' to 'Female'
3. The medical table has 25 rows starting from row X
4. For each row: Read test name from rightmost column, value from next column, etc.
5. Normal ranges are in parentheses format (X-Y)
6. Extract ALL 25 rows from top to bottom"
}}

Be very specific and detailed. This will be used to extract the data correctly.
"""


def get_custom_extraction_prompt(analysis, idx, total_pages):
    """Generate extraction prompt based on the analysis."""
    instructions = analysis.get('extraction_instructions', '')
    total_rows = analysis.get('total_test_rows', 20)
    table_structure = analysis.get('table_structure', '')
    
    return f"""Extract medical data from this report (page {idx}/{total_pages}) following these CUSTOM INSTRUCTIONS:

REPORT ANALYSIS:
- Language: {analysis.get('report_language', 'Unknown')}
- Total test rows in table: {total_rows}
- Table structure: {table_structure}
- Patient info: {analysis.get('patient_info_location', '')}

EXTRACTION INSTRUCTIONS (specific to THIS report):
{instructions}

CRITICAL REQUIREMENTS:
1. Extract ALL {total_rows} rows from the medical table
2. Read normal ranges EXACTLY as shown in the image - do not invent or guess
3. Convert gender to English: ذكر -> "Male", أنثى -> "Female"
4. Return date as YYYY-MM-DD only (no time)

VALIDATION BEFORE RETURNING:
- Does your medical_data array have {total_rows} items? If not, you missed rows!
- Are all normal ranges read from the image (not from your memory)?
- Is gender in English ("Male" or "Female")?

Return JSON:
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
