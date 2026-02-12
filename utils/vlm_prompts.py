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
6. **Doctor Name**: Search the ENTIRE page for the doctor's name:
   - Header: Find the label "الطبيب" in the demographics grid → read the text INSIDE that same box cell. This is the doctor's PERSONAL name.
   - Also check: "Doctor Name", "Physician", "Requesting Doctor", "الطبيب المعالج".
   - Footer/bottom: next to a signature, stamp, "إعداد" (Prepared by), or "المختص" (Specialist).
   - Signature area: a handwritten or printed name near the bottom.
   - ⚠️ ALERT: "عيادة الطب العام" is a clinic, NOT a doctor. "جهة الطلب" is a facility.
   - ✅ The doctor name is a PERSON's name in Arabic or English (e.g., "جهاد العملة", "Ahmad Saleh").
   - If no doctor name found anywhere, return empty string "".

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
4. **LITERAL RANGE**: Capture the "Normal Range" column exactly as written, including brackets and hyphens.   - 🚨 **DECIMAL PRECISION**: Read EVERY digit and decimal point. If the range says "(27-31.2)", write "(27-31.2)" NOT "(27-31)".
   - 🚨 If the range says "(11.5-14.5)", write "(11.5-14.5)" NOT "(115-145)". Watch for decimal points!
   - 🚨 Do NOT round, truncate, or substitute commonly known ranges. Copy the EXACT printed numbers.
5. **EXTRACT ALL ROWS**: Tables can have 20-30+ rows. Scan to the VERY BOTTOM. Do NOT stop early.
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
   - 🚨 DECIMAL PRECISION: Read EVERY digit & decimal in the range. (27-31.2) is NOT (27-31). (140-450) is NOT (150-400). (11.5-14.5) is NOT (115-145).
   - 🚨 ROW-VALUE SANITY: Does the value make sense for the test? (e.g., RDW ~12-15%, NOT 257; Platelets ~150-450 K/uL, NOT 12.6)
7) EXTRACT ALL ROWS: Tables can have 20-30+ rows. Scan ALL the way to the bottom. Do NOT stop early. Tests like Eosinophils, Basophils, MPV, PDW at the bottom MUST be extracted.

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
    VLM reads directly from the image — no OCR anchor priority.
    """
    return """Extract patient and report information from this laboratory document.

🚨 DEMOGRAPHIC GRID MAP (STRICT) 🚨
This report uses a 2-column grid layout for demographics. Labels are on the RIGHT, values are on the LEFT.

🚨🚨 READ DIRECTLY FROM IMAGE — DO NOT GUESS 🚨🚨
You must read every name character-by-character from the image. Do NOT rely on any previously extracted text.
Arabic characters must be read carefully — each dot and letter matters.

1. **PATIENT NAME (اسم المريض)**:
   - Location: Top demographics table, next to label "اسم المريض".
   - 🚨 **EXTREME CHARACTER AWARENESS**: Mirror the INK letter-for-letter. Look closely at dots and "teeth" of letters.
   - 🚨 **ARABIC LETTER DISCRIMINATION** (CRITICAL):
     * Count dots carefully: ب (1 dot below) vs ت (2 dots above) vs ث (3 dots above)
     * خ (dot above) vs ح (no dot) vs ج (dot below)
     * ذ (dot above) vs د (no dot)
     * ض (dot above) vs ص (no dot)
     * ظ (dot above) vs ط (no dot)
     * غ (dot above) vs ع (no dot)
     * ر (no dot) vs ز (dot above)
     * ن (dot above) vs ب (dot below)
     * ك vs ل - different shapes
     * د vs ر - different curves
     * ط (closed loop) vs ل (no loop) - VERY different shapes, do NOT confuse
     * ب (dot below) vs ي (two dots below) vs ن (dot above)
   - 🚨 **HAMZA & TA MARBUTA** (CRITICAL for Arabic names):
     * ئ (hamza on ya) is COMMON in Arabic names like "رئيسة". Do NOT replace with plain ي.
     * ة (ta marbuta / round ta) is the STANDARD ending for Arabic female names. Do NOT replace with ه (ha).
     * أ (hamza on alef) is common at start of names. Keep it as أ, not ا.
   - 🚨 **EACH WORD MATTERS**: Read the LAST word of the name just as carefully as the first. Do NOT skip or rush.
   - 🚨 **SPACING**: "ابو" (Abu) is always separate (e.g., "أبو الرب" NOT "ابوراب").
   - 🚫 Do NOT guess or "correct" the name. Read the EXACT ink.

2. **DOCTOR NAME (الطبيب)**:
   - 🔍 **FIND THE LABEL "الطبيب" IN THE HEADER GRID**: Read the text INSIDE the same cell/box. This text is the doctor's personal name.
   - 🔍 **ALSO SEARCH**: footer, signature area, stamp, "إعداد" (Prepared by), "المختص" (Specialist).
   - 🚨 **READ CHARACTER BY CHARACTER**: The doctor is a PERSON's name (e.g., "جهاد العملة", "أحمد صالح").
   - 🚨 **VOID REJECTION**: "عيادة" (Clinic), "مختبر" (Lab), "وزارة" (Ministry), "مديرية" (Directorate) are NOT doctor names. 
   - 🚫 Do NOT confuse the clinic/facility name with the doctor's personal name.
   - ⚠️ Even if "جهة الطلب" or "عيادة الطب العام" appears NEARBY, the text inside the "الطبيب" box is a separate person's name.
   - If no doctor name is found anywhere on the page, return empty string "".

3. **GENDER (الجنس)**:
   - Find "الجنس" on the right. Value is to the LEFT. (أنثى/انثى -> Female, ذكر -> Male).

4. **REPORT DATE**:
   - Extract the date from the header.
   - 🚨 **DATE FORMAT RULE**: 
     - If the report is in Arabic, interpret "XX/XX/YYYY" as **DD/MM/YYYY**.
     - If the report is in English, interpret "XX/XX/YYYY" as **MM/DD/YYYY**.
   - Convert to standard **YYYY-MM-DD** for the JSON output.

5. **REPORT NAME & TYPE**:
   - Identify the specific title of the report (e.g., "Complete Blood Count", "Biochemistry Report").
   - 🚨 **MULTI-SECTION REPORTS**: If the report has MULTIPLE sections (e.g., both "HEMATOLOGY" and "CLINICAL CHEMISTRY"), 
     list ALL section names separated by " & " (e.g., "HEMATOLOGY & CLINICAL CHEMISTRY").
   - 🚨 **REPORT TYPE CATEGORY**: You MUST pick EXACTLY ONE from this list: [`Lab results`, `Prescriptions`, `Imaging`, `Cardiology`, `Neurology`, `Orthopedic`].
   - If it is a blood test, urine test, or biopsy, it is ALWAYS `Lab results`.

6. **PARAMETER DEDUPLICATION BIAS**:
   - If you see two rows for "Neutrophils" (one as absolute count, one as percent), you MUST output BOTH separately.
   - Do NOT merge "Neutrophils" and "Neutrophils %" or "Lymphocytes" and "Lymphocytes %".

Return JSON only:
{
    "patient_name": "Read EXACT characters from image next to اسم المريض. Letter by letter.",
    "patient_age": "If explicit age field exists, use that number. Otherwise extract Date of Birth (تاريخ الميلاد) as DD/MM/YYYY.",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD",
    "report_name": "Full title of the report as written (e.g. CBC)",
    "report_type": "Category of report (e.g. Haematology)",
    "doctor_names": "Search ENTIRE page: header, footer, signature, stamp. Return person name only, or empty string."
}"""


def get_name_verification_demographics_prompt(ocr_patient_name: str, ocr_doctor_name: str = "") -> str:
    """
    Demographics prompt that uses OCR-extracted name as anchor for VLM verification.
    Instead of reading from scratch (which causes inconsistency for Arabic),
    the VLM verifies/corrects the OCR-extracted name letter by letter.
    """
    return f"""Extract patient and report information from this laboratory document.

🚨 NAME VERIFICATION MODE (CRITICAL) 🚨
OCR has already extracted the patient name as: **"{ocr_patient_name}"**
{"OCR has extracted the doctor name as: **" + chr(34) + ocr_doctor_name + chr(34) + "**" if ocr_doctor_name else ""}

Your task is to VERIFY this name against the image:

1. **PATIENT NAME (اسم المريض)**:
   - Find the cell next to "اسم المريض" in the header.
   - Read each character of the name in the image, one by one.
   - Compare with the OCR name "{ocr_patient_name}" character by character.
   - If the OCR name matches what you see in the image → USE IT EXACTLY.
   - If there are minor differences (1-2 characters) → CORRECT only the wrong characters.
   - If the OCR name is completely wrong → Read the name fresh from the image.
   - 🚨 **ARABIC LETTER DISCRIMINATION** (CRITICAL):
     * Count dots carefully: ب (1 dot below) vs ت (2 dots above) vs ث (3 dots above)
     * خ (dot above) vs ح (no dot) vs ج (dot below)
     * ذ (dot above) vs د (no dot)
     * ض (dot above) vs ص (no dot)
     * ظ (dot above) vs ط (no dot)
     * غ (dot above) vs ع (no dot)
     * ر (no dot) vs ز (dot above)
     * ن (dot above) vs ب (dot below)
     * ط (closed loop) vs ل (no loop) - VERY different shapes, do NOT confuse
     * ب (dot below) vs ي (two dots below) vs ن (dot above)
   - 🚨 **HAMZA & TA MARBUTA** (CRITICAL for Arabic names):
     * ئ (hamza on ya) is COMMON in names like "رئيسة". Do NOT replace with plain ي.
     * ة (ta marbuta) is the STANDARD ending for Arabic female names. Do NOT replace with ه (ha).
     * أ (hamza on alef) is common at start of names. Keep it as أ, not ا.
   - 🚨 **EACH WORD MATTERS**: Read every word of the name with equal care, especially the LAST word.
   - 🚫 Do NOT guess or invent a name. If you cannot read it clearly, use the OCR version.

2. **DOCTOR NAME (الطبيب)**:
   - 🔍 **FIND THE LABEL "الطبيب" IN THE HEADER GRID** → read the text INSIDE that same cell. It is a person's name.
   - 🔍 **ALSO SEARCH**: footer, signature, stamp, "إعداد", "المختص".
   {"- OCR read it as: " + chr(34) + ocr_doctor_name + chr(34) + ". Verify against the image." if ocr_doctor_name else "- Read the name directly from the image."}
   - 🚫 "عيادة" (Clinic), "مختبر" (Lab), "وزارة" (Ministry), "مديرية" (Directorate) are NOT doctor names.
   - ⚠️ Even if "جهة الطلب" or "عيادة الطب العام" appears NEARBY, the text inside the "الطبيب" box is a separate person's name.
   - If no doctor name is found anywhere on the page, return empty string "".

3. **GENDER (الجنس)**:
   - Find "الجنس". (أنثى/انثى → Female, ذكر → Male).

4. **REPORT DATE**:
   - Arabic reports: "XX/XX/YYYY" = DD/MM/YYYY. Convert to YYYY-MM-DD.

5. **REPORT NAME & TYPE**:
   - Report type: EXACTLY ONE of [`Lab results`, `Prescriptions`, `Imaging`, `Cardiology`, `Neurology`, `Orthopedic`].
   - If multiple sections exist (e.g., both "HEMATOLOGY" and "CLINICAL CHEMISTRY"), combine with " & ".

Return JSON only:
{{
    "patient_name": "Verified/corrected name from image",
    "patient_age": "If explicit age exists, use it. Otherwise extract Date of Birth (تاريخ الميلاد) as DD/MM/YYYY.",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD",
    "report_name": "Full title of the report",
    "report_type": "Lab results",
    "doctor_names": "Verified/corrected doctor name"
}}"""
