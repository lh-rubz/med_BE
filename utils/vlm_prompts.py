"""VLM prompts for patient info and lab table extraction."""


def get_personal_info_prompt(idx, total_pages):
    """Prompt to extract ONLY patient personal info using Inside-Box Adjacency."""
    return f"""You are an expert medical document digitizer.
Task: Extract PATIENT & DOCTOR information (page {idx}/{total_pages}).

🚨 INSIDE-BOX ADJACENCY RULE (CRITICAL) 🚨
Find the following labels in the top grids. For each label, you MUST ONLY extract the text found **physically inside the same rectangular box**.
- **RULE**: If a box contains a label (e.g. 'اسم المريض') and nothing else, return 'Unknown'.
- **RULE**: DO NOT look at other boxes. DO NOT 'jump' to text in different parts of the grid.

REQUIRED FIELDS:
1. **Patient Name**: Text physically INSIDE the same box as "اسم المريض".
2. **ID Number**: Text INSIDE the same box as "رقم الهوية".
3. **Gender**: Text INSIDE the box for "الجنس". (أنثى -> Female, ذكر -> Male).
4. **DOB**: Text INSIDE the box for "تاريخ الميلاد".
5. **Order Date**: Text INSIDE the box for "تاريخ الطلب". Extract as YYYY-MM-DD.
6. **Doctor Name**: Text INSIDE the box for "الطبيب".
   - ⚠️ ALERT: "عيادة الطب العام" is a clinic, NOT a doctor. "جهة الطلب" is a facility. Extract ONLY the person's name (e.g., جهاد العملة).

JSON OUTPUT ONLY:
{{
  "patient_name": "",
  "patient_age": "",
  "patient_dob": "",
  "patient_gender": "",
  "report_date": "",
  "doctor_names": ""
}}
"""


def get_main_vlm_prompt(idx, total_pages):
    """Prompt to extract LAB TABLE data with Horizontal Band Lock."""
    return f"""You are a high-precision lab data digitizer.
Task: Extract LAB DATA (page {idx}/{total_pages}).

🚨 HORIZONTAL BAND LOCK (CRITICAL) 🚨
1. **IDENTIFY COLUMNS**: From Right to Left, the columns are: [Test Name | Result | Normal Range | Unit | Notes].
2. **ONE BAND AT A TIME**: For each Test Name, stay strictly within its horizontal band.
3. **"EMPTY_SPECIFIED"**: If the Result column is empty or only contains a symbol (`*`) within the horizontal band of a test, you MUST return `field_value`: "EMPTY_SPECIFIED".
   - **NEVER** pull a value from a different horizontal line. This is why Take 5 failed!
4. **LITERAL RANGE**: Capture the "Normal Range" column exactly as written, including brackets and hyphens.

VALIDATION:
- Produced JSON must contain one entry for every physical row in the table.

JSON OUTPUT ONLY:
{{
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


def get_table_retry_prompt(idx, total_pages):
    """Fallback prompt focused on table alignment with duplicate-range self-check."""
    return f"""You are reading a lab report image (page {idx}/{total_pages}) in Arabic or English.
Focus ONLY on table rows. Return exactly one JSON object with medical_data.

CRITICAL ALIGNMENT RULES
1) Vertical Column Boundaries: Each table has clear vertical lines separating columns.
   - Do NOT cross these boundaries.
   - Column 1 = Test Names (far left)
   - Column 2 = Values (after first vertical line)
   - Column 3 = Units (after second vertical line)
   - Column 4 = Normal Range (after third vertical line)

2) Horizontal Row Boundaries: Each row has a clear horizontal space or line separating it from adjacent rows.
   - Trace across ONE row at a time.
   - Read each column value ONLY from within that row's horizontal band.

3) One row at a time. Follow the horizontal line even if slanted.
4) If a cell in THIS row is empty or a symbol (-, *, .), return "" for that cell.
5) Do NOT copy values/ranges from other rows. Never invent values.
6) MISALIGNMENT CHECK: Before returning, verify that:
   - Each field_value is a number or qualitative text (NOT a %, unit, or range)
   - Each field_unit is a medical unit (NOT a number, range, or percentage symbol alone)
   - Each normal_range is a range like (X-Y) (NOT a number or unit)
   - If any two different tests share the EXACT same range AND same unit -> re-check alignment.

READING STEPS PER ROW
- field_name: test column in THIS row. Must be a medical test name.
- field_value: result column same row; if empty/-/*/blank -> "".
  (If field_value is empty, SKIP THIS ROW entirely—do not add it to medical_data).
- field_unit: unit column same row. Must be a medical unit abbreviation.
- normal_range: range column same row; if empty/-/(-)/*/symbol-only -> "".
  (If the report shows an empty range, leave it empty. Do NOT invent ranges.)
- is_normal: null if value or range empty; else true/false only if numbers present.

FINAL CHECK
- value should NOT contain % or unit symbols
- unit should NOT contain numbers, ranges, or value-like content
- range should NOT contain just a single number
- If this check FAILS, recheck the row alignment

OUTPUT: Only rows with non-empty field_name AND non-empty field_value.

JSON OUTPUT ONLY:
{{
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


def generate_prompt_for_page(page_text, page_idx, total_pages):
    """Generate a prompt for extracting structured medical data from a report page.
    
    Args:
        page_text: The text content of the page
        page_idx: Current page index
        total_pages: Total number of pages
        
    Returns:
        A formatted prompt string with properly escaped JSON template
    """
    return f"""
    TASK: Extract medical data from the report page.

    PAGE INDEX: {page_idx}/{total_pages}

    PAGE CONTENT:
    {page_text}

    INSTRUCTIONS:
    1. Group data by sections (e.g., Haematology Report, Biochemistry).
    2. Extract all medical fields with their values, units, and normal ranges.
    3. Extract doctor names and ensure they are complete.
    4. For each field, calculate and set "is_normal" based on the value and range.
    5. Ensure all extracted data is accurate and matches the page content.
    6. Handle both Arabic and English text correctly.

    OUTPUT FORMAT:
    {{{{
        "sections": [
            {{{{
                "section_name": "Haematology Report",
                "fields": [
                    {{{{
                        "field_name": "",
                        "field_value": "",
                        "field_unit": "",
                        "normal_range": "",
                        "is_normal": null,
                        "notes": ""
                    }}}}
                ]
            }}}}
        ],
        "doctor_names": ""
    }}}}
    """


def get_robust_demographics_prompt():
    """
    Consolidated high-precision demographic extraction prompt.
    Targets grid layouts, labels-to-right, and specific Arabic medical terminology.
    """
    return """Extract patient and report information from this laboratory document.

🚨 DEMOGRAPHIC GRID MAP (STRICT) 🚨
This report uses a 2-column grid layout for demographics. Labels are on the RIGHT, values are on the LEFT.

🚨🚨 OCR ANCHOR PRIORITY 🚨🚨
The OCR system has already captured the patient and doctor names. Your job is to VERIFY they match the image, NOT to REPLACE them.
If the OCR already has a name, KEEP IT unless the image CLEARLY and UNAMBIGUOUSLY shows DIFFERENT characters.
Do NOT "correct" names based on guessing — OCR typed text is more reliable than your visual reading of Arabic.

1. **PATIENT NAME (اسم المريض)**:
   - Location: Top demographics table, next to label "اسم المريض".
   - 🚨 **MIRROR PERFECT SPELLING**: Copy the exact characters from the report. Do NOT hallucinate or change letters.
   - 🚨 **SPACING**: "ابو" (Abu) is always separate (e.g., "أبو الرب" NOT "ابوراب").
   - If OCR already captured a name, KEEP IT unless image clearly shows different text.

2. **DOCTOR NAME (الطبيب)**:
   - 🔍 Look at the cell next to the label "الطبيب" (Doctor) in the header grid.
   - 🚨 **VOID REJECTION**: "عيادة" (Clinic), "مختبر" (Lab), "وزارة" (Ministry) are NOT doctor names. 
   - 🚨 **MIRROR PERFECT SPELLING**: Do NOT change letters. Copy exactly what is written.
   - If OCR already captured a doctor name, KEEP IT — do not replace with a different reading.

3. **GENDER (الجنس)**:
   - Find "الجنس" on the right. Value is to the LEFT. (أنثى/انثى -> Female, ذكر -> Male).

4. **REPORT DATE**:
   - Extract the date from the header.
   - 🚨 **DATE FORMAT RULE**: 
     - If the report is in Arabic, interpret "XX/XX/YYYY" as **DD/MM/YYYY**.
     - If the report is in English, interpret "XX/XX/YYYY" as **MM/DD/YYYY**.
   - Convert to standard **YYYY-MM-DD** for the JSON output.

Return JSON only:
{
    "patient_name": "Exact name from report. Do NOT change OCR-captured name unless image clearly differs.",
    "patient_age": "Literal age or DOB",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD",
    "doctor_names": "Exact doctor name from report. Do NOT change OCR-captured name unless its wrong."
}"""
