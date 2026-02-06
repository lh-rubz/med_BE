"""
LLM-based OCR Text Organizer

Stage 1 of two-stage extraction:
1. OCR extracts raw text from image
2. LLM organizes messy OCR text into structured format (THIS MODULE)
3. VLM extracts final data using organized text + image

Benefits:
- No external NER dependencies
- Handles Arabic + English mixed text
- Can fix OCR errors intelligently
- Works with any report format
"""


def get_text_organizer_prompt():
    """
    Prompt for Stage 1: Organize raw OCR text into structured sections.
    This is a TEXT-ONLY prompt (no image) for faster processing.
    """
    return """You are an expert at organizing messy OCR text from medical lab reports.

Your task: Take the raw OCR text below and organize it into a clean, structured format.

IMPORTANT RULES:
1. DO NOT invent or guess any data - only organize what's in the text
2. Fix obvious OCR errors (e.g., "Glurose" → "Glucose", "0.B" → "0.8")
3. Handle both Arabic (RTL) and English (LTR) text
4. Separate patient information from test results
5. Keep original values exactly as they appear (don't calculate or convert)

CRITICAL FOR ARABIC TABLES:
Arabic lab reports have columns in RIGHT-TO-LEFT order:
- RIGHTMOST column = Test Name (الفحص)
- Next column to left = Result/Value (النتيجة) - THIS IS THE NUMERIC RESULT (e.g., 109, 0.56, 12.6)
- Next column to left = Normal Range (النتيجة الطبيعية) - contains dash like "74-110", "(0.5-0.9)"
- Next column to left = Unit (الوحدة) - like mg/dL, U/L, %
- LEFTMOST column = Notes (ملاحظات)

1-OFF ERROR & MULTI-LINE PREVENTION:
- MULTI-LINE NAMES: Some test names are long and wrap to the next line (e.g., "Red blood cell distribution\nwidth coefficient of variation"). UNITE them into one name.
- Labels like "of variation", "(CBC)", or "Granuloc" on a line by themselves should be MERGED with the test name above them.
- The VALUE is typically aligned with the LAST line of a multi-line name.
- IF a line has text but NO numeric result, it's likely part of a name or a header.
- The VALUE is a single number. The RANGE has a dash or parentheses.

When you see a table row like:
"mg/dL (74-110) 109 Fasting Blood Sugar"
Reading RIGHT-TO-LEFT:
- Test Name: Fasting Blood Sugar
- Result: 109
- Range: (74-110)
- Unit: mg/dL

OUTPUT FORMAT (use this exact structure):

===PATIENT INFORMATION===
Patient Name: look for "اسم المريض" (Patient Name). In Arabic reports, names are often 4+ words (e.g., "هبة جمال ابو الرب"). 
🚨 CRITICAL: DO NOT truncate names. If you see "ابو" (Abu), you MUST include the word that follows it. Capture at least 4 words if visible.
CRITICAL: DO NOT take "شؤون اجتماعية" (Social Case) or "Social" as the patient name. That is the Insurance type.
Patient ID: ID number if found
Gender: Male/Female - look for "الجنس", "Gender", "Sex", "ذكر"=Male, "أنثى"=Female
Age: number only - look for "العمر", "Age", or number followed by "years"/"سنة"
Date of Birth: YYYY-MM-DD or DD/MM/YYYY - look for "تاريخ الميلاد", "DOB", "Date of Birth"
Report Date: YYYY-MM-DD or DD/MM/YYYY - look for "تاريخ التقرير", "Date", "Report Date", date near top
Doctor Name: doctor name - look for "الطبيب", "Doctor", "Dr.", "Physician"
Lab Name: laboratory name if found

===MEDICAL DATA TABLE===
Identify all laboratory tests/fields from the table. 

🚨 SUB-HEADINGS (IMPORTANT):
- If the report has bold sub-headings (e.g., "Investigation", "Biochemistry", "Complete Blood Picture"), and tests are listed under them, you MUST prepend the sub-heading to the test name.
- e.g., "Complete Blood Picture: Haemoglobin".

🚨 NO-RESULT & HEADER RULES:
- 🚫 **IGNORE TABLE HEADERS**: Do NOT extract words like "Investigation", "Result", "Normal Ranges", "Units", "النتيجة", "الفحص", "الوحدة", "ملاحظات" if they are just column labels.
- 🚫 **NO DUPLICATES**: DO NOT list the same test twice in the medical data table. If a test appears multiple times in the OCR, only list it once with its final result.
- DO NOT extract category headers as a test if the line contains no numbers or symbols next to it.

For each test, extract:
- Test name (field_name) - INCLUDE any grouped prefix if applicable.
- Result (field_value) - INCLUDE symbols like "<" or ">" if they are part of the value.
- Unit (field_unit)
- Normal range (normal_range)
- Category (e.g. CBC, Liver, etc.)
- Normal Range contains a dash or parentheses (e.g., "74-110", "(0.5-0.9)")
- DO NOT confuse Value with Normal Range!
- DO NOT put square brackets around names or values

VALIDATION:
- Value should be a simple number (e.g., 109, 0.56, 12.6)
- Normal Range contains a dash or parentheses (e.g., "74-110", "(0.5-0.9)")
- DO NOT confuse Value with Normal Range!
- DO NOT put square brackets around names or values (e.g., use "12.5" NOT "[12.5]")

---
RAW OCR TEXT TO ORGANIZE:
"""


def get_enhanced_extraction_prompt(organized_text, page_idx, total_pages):
    """
    Prompt for Stage 2: Extract structured JSON using organized text + image.
    The organized text helps the VLM focus on correct values.
    """
    return f"""You are extracting medical data from a lab report image (page {page_idx}/{total_pages}).

I have pre-processed the OCR text into an organized format below. Use this AS A GUIDE, but VERIFY against the image.

PRE-ORGANIZED TEXT:
{organized_text}

🚨 CRITICAL: ARABIC TABLE COLUMN ORDER (RIGHT-TO-LEFT) 🚨

This is an Arabic medical report. The table columns read RIGHT-TO-LEFT:

| ملاحظات | الوحدة | النتيجة الطبيعية | النتيجة | الفحص |
| Notes   | Unit   | Normal Range     | Result  | Test  |
| (LEFT)  |   ←    |       ←          |    ←    | (RIGHT)|

For example, a row showing: "mg/dL | (74-110) | 109 | | Fasting Blood Sugar (FBS)"
Reading RIGHT-TO-LEFT:
- Test Name (الفحص): "Fasting Blood Sugar (FBS)" (rightmost)
- Result (النتيجة): "109" (the NUMERIC VALUE - second from right)
- Normal Range (النتيجة الطبيعية): "(74-110)" (middle - contains dash/parentheses)
- Unit (الوحدة): "mg/dL" (second from left)

🔴 COMMON MISTAKES TO AVOID:
- DO NOT put the range "(74-110)" as the value - that's the NORMAL RANGE
- DO NOT put the value "109" as the range
- The VALUE is always a simple number: 109, 0.56, 12.6, 230
- The RANGE always has a dash or slash: 74-110, (0.5-0.9), 0-200

EXTRACTION RULES:
1. Read each row RIGHT-TO-LEFT
2. field_value = The numeric result (second column from right)
3. normal_range = The reference range with dashes (middle column)
4. field_unit = The unit abbreviation (second column from left)
5. Extract EVERY row - do not stop early

OUTPUT (JSON only, no markdown):
{{{{
  "patient_name": "",
  "patient_age": "",
  "patient_gender": "",
  "report_date": "",
  "doctor_names": "",
  "report_name": "",
  "report_type": "",
  "medical_data": [
    {{{{
      "field_name": "Test name from rightmost column",
      "field_value": "Numeric result (e.g., 109, 0.56, NOT a range)",
      "field_unit": "Unit from second-left column",
      "normal_range": "Range with dash (e.g., 74-110, 0.5-0.9)"
    }}}}
  ]
}}}}
"""


def parse_organized_text(organized_text):
    """
    Parse the LLM-organized text into a structured dictionary.
    Enhanced to handle multiple date formats and Arabic text.
    """
    import re
    
    result = {
        'patient_name': '',
        'patient_gender': '',
        'patient_age': '',
        'patient_dob': '',
        'report_date': '',
        'doctor_names': '',
        'patient_id': '',
        'lab_name': '',
        'medical_data': []
    }
    
    if not organized_text:
        return result
    
    def clean_value(val):
        """Clean extracted value - remove NOT FOUND and trim"""
        if not val:
            return ''
        val = val.strip()
        if 'NOT FOUND' in val.upper() or 'N/A' in val.upper() or val == '-':
            return ''
        return val
    
    def normalize_date(date_str):
        """Convert various date formats to YYYY-MM-DD"""
        if not date_str:
            return ''
        date_str = date_str.strip()
        # Try DD/MM/YYYY
        match = re.match(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', date_str)
        if match:
            d, m, y = match.groups()
            return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        # Try YYYY-MM-DD or YYYY/MM/DD
        match = re.match(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', date_str)
        if match:
            y, m, d = match.groups()
            return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        return date_str
    
    # Extract patient information section
    patient_section = re.search(r'===PATIENT INFORMATION===(.*?)(?:===|$)', organized_text, re.DOTALL)
    if patient_section:
        section_text = patient_section.group(1)
        
        # Patient Name - multiple patterns
        name_match = re.search(r'Patient Name:\s*(.+?)(?:\n|$)', section_text)
        if name_match:
            result['patient_name'] = clean_value(name_match.group(1))
        
        # Patient ID
        id_match = re.search(r'Patient ID:\s*(.+?)(?:\n|$)', section_text)
        if id_match:
            result['patient_id'] = clean_value(id_match.group(1))
        
        # Gender - handle Arabic
        gender_match = re.search(r'Gender:\s*(.+?)(?:\n|$)', section_text)
        if gender_match:
            gender = clean_value(gender_match.group(1))
            if gender:
                gender_lower = gender.lower()
                if gender_lower in ['male', 'm', 'ذكر', 'male/ذكر']:
                    result['patient_gender'] = 'Male'
                elif gender_lower in ['female', 'f', 'أنثى', 'انثى', 'female/أنثى']:
                    result['patient_gender'] = 'Female'
                else:
                    result['patient_gender'] = gender
        
        # Age - extract number only
        age_match = re.search(r'Age:\s*(\d+)', section_text)
        if age_match:
            result['patient_age'] = age_match.group(1)
        
        # DOB - multiple date formats
        dob_match = re.search(r'Date of Birth:\s*([\d/\-]+)', section_text)
        if dob_match:
            result['patient_dob'] = normalize_date(clean_value(dob_match.group(1)))
        
        # Report Date - multiple date formats
        date_match = re.search(r'Report Date:\s*([\d/\-]+)', section_text)
        if date_match:
            result['report_date'] = normalize_date(clean_value(date_match.group(1)))
        
        # Doctor Name
        doctor_match = re.search(r'Doctor Name:\s*(.+?)(?:\n|$)', section_text)
        if doctor_match:
            result['doctor_names'] = clean_value(doctor_match.group(1))
        
        # Lab Name
        lab_match = re.search(r'Lab Name:\s*(.+?)(?:\n|$)', section_text)
        if lab_match:
            result['lab_name'] = clean_value(lab_match.group(1))
    
    # Extract medical tests section
    tests_section = re.search(r'===MEDICAL TESTS===(.*?)(?:===|$)', organized_text, re.DOTALL)
    if tests_section:
        section_text = tests_section.group(1)
        
        buffered_name = ""
        # Parse pipe-separated rows
        for line in section_text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Handle lines without pipes as part of a multi-line name
            if '|' not in line:
                if len(line) > 2:
                    buffered_name = (buffered_name + " " + line).strip()
                continue
            
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 2:
                current_name = parts[0] if parts[0] and 'NOT FOUND' not in parts[0].upper() else ''
                current_value = parts[1] if len(parts) > 1 and 'NOT FOUND' not in parts[1].upper() else ''
                
                # If we have a buffered name, prepend it to current name
                if buffered_name:
                    full_name = (buffered_name + " " + current_name).strip()
                    buffered_name = ""
                else:
                    full_name = current_name
                
                field = {
                    'field_name': full_name,
                    'field_value': current_value,
                    'field_unit': parts[2] if len(parts) > 2 and 'NOT FOUND' not in parts[2].upper() else '',
                    'normal_range': parts[3] if len(parts) > 3 and 'NOT FOUND' not in parts[3].upper() else ''
                }
                
                # If name exists but no value, buffer the name and continue
                if field['field_name'] and not field['field_value']:
                    buffered_name = field['field_name']
                    continue
                
                # Only add if we have both name and value
                if field['field_name'] and field['field_value']:
                    result['medical_data'].append(field)
    
    return result
