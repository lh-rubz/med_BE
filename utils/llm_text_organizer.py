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


def get_text_organizer_prompt(focus_on_table: bool = False):
    """
    Prompt for Stage 1: Organize raw OCR text into structured sections.
    Focuses on creating high-quality "Anchors" for Stage 2 VLM refinement.
    """
    demographics_section = "" if focus_on_table else """
===PATIENT INFORMATION===
Patient Name: [Capture FULL name, 🚨 2+ words, NO TRUNCATION]
Doctor Name: [🔍 SCAN WHOLE TEXT, logo area, stamps, etc.]
Age: [Value]
Gender: [Male/Female]
Report Date: [DD/MM/YYYY or MM/DD/YYYY]
"""

    return f"""You are an expert at organizing messy OCR text from medical lab reports.

Your task: Take the raw OCR text below and organize it into clean "Anchors" that will be used for visual verification.

IMPORTANT RULES:
1. **FOCUS ON NAMES**: The most important task is capturing every Test Name correctly.
2. **UNITE MULTI-LINE NAMES**: Some test names wrap to multiple lines. UNITE them (e.g., "Red blood cell \n distribution width" → "Red blood cell distribution width").
3. **DO NOT GUESS VALUES**: Only organize what is in the text. If a value looks misaligned, keep it as is; Stage 2 will fix it visually.
4. **NO RANGE BLEEDING**: Strictly keep "Normal Range" separate from "Test Name".
   - Bad: "Monocytes (% (1.0-3.0)"
   - Good: Name="Monocytes (%)", Range="(1.0-3.0)"
5. 🚨 **PREFIX PROTECTION**: If a test starts with a letter and dash (e.g., "C - Reactive Proteins", "S - Albumin"), YOU MUST capture the "C -" as part of the Test Name. NEVER put "C" in the Result column.
6. 🚨 **UNIT FIDELITY**: If the text says "%L" or "%G", **DO NOT** simplify it to "%". Capture every character of the unit exactly as written.

{demographics_section}

===MEDICAL DATA TABLE===
List every test found in this exact format:
Test Name | Result | Unit | Normal Range

- If a line is just a header (no numeric result), IGNORE it unless it's a sub-heading (prepend it to the tests below it).
- If Result is missing, leave it blank between the pipes.

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
    
    # Detection of Arabic text for conditional date parsing
    # Arabic: DD/MM/YYYY, English: MM/DD/YYYY
    has_arabic = any('\u0600' <= char <= '\u06FF' for char in organized_text)
    
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
        
        # Try XX/XX/YYYY (Conditional logic based on has_arabic)
        match = re.match(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', date_str)
        if match:
            v1, v2, y = match.groups()
            if has_arabic:
                # Arabic: DD/MM/YYYY
                d, m = v1, v2
            else:
                # English: MM/DD/YYYY
                m, d = v1, v2
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
    tests_section = re.search(r'===MEDICAL DATA TABLE===(.*?)(?:===|$)', organized_text, re.DOTALL)
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
