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

OUTPUT FORMAT (use this exact structure):

===PATIENT INFORMATION===
Patient Name: [extracted name or "NOT FOUND"]
Gender: [Male/Female/NOT FOUND]
Age: [number or "NOT FOUND"]
Date of Birth: [YYYY-MM-DD or "NOT FOUND"]
Report Date: [YYYY-MM-DD or "NOT FOUND"]
Doctor Name: [extracted name or "NOT FOUND"]

===MEDICAL TESTS===
[Test Name] | [Value] | [Unit] | [Normal Range]
[Test Name] | [Value] | [Unit] | [Normal Range]
...

EXAMPLE INPUT:
"اسم المريض خضر طالب  الجنس ذكر العمر 45  Glucose  98  mg/dL  70-110  Creatinine  0.8  mg/dL"

EXAMPLE OUTPUT:
===PATIENT INFORMATION===
Patient Name: خضر طالب
Gender: Male
Age: 45
Date of Birth: NOT FOUND
Report Date: NOT FOUND
Doctor Name: NOT FOUND

===MEDICAL TESTS===
Glucose | 98 | mg/dL | 70-110
Creatinine | 0.8 | mg/dL | NOT FOUND

---
RAW OCR TEXT TO ORGANIZE:
"""


def get_enhanced_extraction_prompt(organized_text, page_idx, total_pages):
    """
    Prompt for Stage 2: Extract structured JSON using organized text + image.
    The organized text helps the VLM focus on correct values.
    """
    return f"""You are extracting medical data from a lab report image (page {page_idx}/{total_pages}).

I have pre-processed the OCR text into an organized format below. Use this AS A GUIDE, but verify against the image.

PRE-ORGANIZED TEXT:
{organized_text}

YOUR TASK:
1. Look at the IMAGE to verify the organized text is correct
2. Extract ALL test results into the JSON format below
3. If the organized text has errors, trust the IMAGE
4. Extract EVERY row from the table - do not stop early

CRITICAL RULES:
- Each test result must come from the SAME ROW (don't mix values)
- field_value must be the NUMERIC RESULT only (not the range)
- normal_range is the reference range (e.g., "70-110", "(0.6-1.2)")
- If organized text shows "NOT FOUND", look harder in the image

OUTPUT (JSON only, no markdown):
{{
  "patient_name": "",
  "patient_age": "",
  "patient_gender": "",
  "report_date": "",
  "doctor_names": "",
  "report_name": "",
  "report_type": "",
  "medical_data": [
    {{
      "field_name": "Test name",
      "field_value": "Numeric result",
      "field_unit": "Unit",
      "normal_range": "Reference range"
    }}
  ]
}}
"""


def parse_organized_text(organized_text):
    """
    Parse the LLM-organized text into a structured dictionary.
    Useful for fallback if VLM fails.
    """
    import re
    
    result = {
        'patient_name': '',
        'patient_gender': '',
        'patient_age': '',
        'patient_dob': '',
        'report_date': '',
        'doctor_names': '',
        'medical_data': []
    }
    
    if not organized_text:
        return result
    
    # Extract patient information section
    patient_section = re.search(r'===PATIENT INFORMATION===(.*?)(?:===|$)', organized_text, re.DOTALL)
    if patient_section:
        section_text = patient_section.group(1)
        
        # Patient Name
        name_match = re.search(r'Patient Name:\s*(.+?)(?:\n|$)', section_text)
        if name_match and 'NOT FOUND' not in name_match.group(1).upper():
            result['patient_name'] = name_match.group(1).strip()
        
        # Gender
        gender_match = re.search(r'Gender:\s*(.+?)(?:\n|$)', section_text)
        if gender_match:
            gender = gender_match.group(1).strip()
            if 'NOT FOUND' not in gender.upper():
                # Normalize gender
                if gender.lower() in ['male', 'm', 'ذكر']:
                    result['patient_gender'] = 'Male'
                elif gender.lower() in ['female', 'f', 'أنثى', 'انثى']:
                    result['patient_gender'] = 'Female'
        
        # Age
        age_match = re.search(r'Age:\s*(\d+)', section_text)
        if age_match:
            result['patient_age'] = age_match.group(1)
        
        # DOB
        dob_match = re.search(r'Date of Birth:\s*(\d{4}-\d{2}-\d{2})', section_text)
        if dob_match:
            result['patient_dob'] = dob_match.group(1)
        
        # Report Date
        date_match = re.search(r'Report Date:\s*(\d{4}-\d{2}-\d{2})', section_text)
        if date_match:
            result['report_date'] = date_match.group(1)
        
        # Doctor
        doctor_match = re.search(r'Doctor Name:\s*(.+?)(?:\n|$)', section_text)
        if doctor_match and 'NOT FOUND' not in doctor_match.group(1).upper():
            result['doctor_names'] = doctor_match.group(1).strip()
    
    # Extract medical tests section
    tests_section = re.search(r'===MEDICAL TESTS===(.*?)(?:===|$)', organized_text, re.DOTALL)
    if tests_section:
        section_text = tests_section.group(1)
        
        # Parse pipe-separated rows
        for line in section_text.strip().split('\n'):
            line = line.strip()
            if not line or '|' not in line:
                continue
            
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 2:
                field = {
                    'field_name': parts[0] if parts[0] and 'NOT FOUND' not in parts[0].upper() else '',
                    'field_value': parts[1] if len(parts) > 1 and 'NOT FOUND' not in parts[1].upper() else '',
                    'field_unit': parts[2] if len(parts) > 2 and 'NOT FOUND' not in parts[2].upper() else '',
                    'normal_range': parts[3] if len(parts) > 3 and 'NOT FOUND' not in parts[3].upper() else ''
                }
                
                # Only add if we have at least name and value
                if field['field_name'] and field['field_value']:
                    result['medical_data'].append(field)
    
    return result
