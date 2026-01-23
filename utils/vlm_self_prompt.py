"""Self-prompting: Let the model create its own extraction prompt after analyzing the report."""
import json

def get_report_analysis_prompt(idx, total_pages):
    """Ask the model to analyze the report and create a custom extraction prompt."""
    return f"""🚨 MEDICAL REPORT ANALYSIS TASK 🚨

You are analyzing page {idx}/{total_pages} of a medical lab report.

🎯 YOUR MISSION: COUNT EVERY SINGLE ROW IN THE MEDICAL TABLE

STEP 1 - COUNT THE ROWS AND IDENTIFY LANGUAGES:
Look at the medical data table in the image. Starting from the first test row, COUNT each row and note the language:
- Row 1: [test name in English or Arabic?]
- Row 2: [test name]
- Row 3: [test name]
...continue until the last row

For EACH row, also note:
- Is the test name in ENGLISH (e.g., "Glucose", "Cholesterol") or ARABIC (e.g., "الغلوكوز", "الكولسترول")?
- Are values clearly separated from units?
- Is there a normal range shown in parentheses like (74-110) or is it EMPTY/missing?

⚠️ DO NOT STOP AT 5 OR 10 ROWS - COUNT THEM ALL!
⚠️ If you see 24+ rows, your answer should be 24+, not 6!
⚠️ THIS IS PAGE {idx} OF {total_pages} - CONTINUE EXTRACTION ACROSS ALL PAGES!
⚠️ DO NOT INVENT NORMAL RANGES - if empty in image, leave it empty in JSON!

STEP 2 - ANALYZE THE TABLE STRUCTURE:
1. Language: Is it Arabic, English, or bilingual?
2. Column positions (right-to-left or left-to-right?):
   - Which column has TEST NAMES?
   - Which column has RESULTS/VALUES?
   - Which column has UNITS?
   - Which column has NORMAL RANGES?
3. Patient info location:
   - Where is patient name? (after 'اسم المريض' or 'Patient Name') - NOTE THE EXACT TEXT AND LANGUAGE
   - Where is gender? (If Arabic: ذكر=Male, أنثى=Female) - CONVERT TO ENGLISH
   - Where is date?
4. Doctor/Lab info location:
   - Where is doctor name? (look for 'دكتور', 'طبيب', 'Doctor', 'DR', 'Dr.' or signature) - IMPORTANT: MUST RETURN THIS
   - Where is lab name or clinic name?
   - Is there a signature area at bottom or top?

STEP 3 - CREATE ROW-BY-ROW EXTRACTION MAP:
List the FIRST 5 ROWS and LAST 5 ROWS you can see:
First 5:
1. [Test name from row 1]
2. [Test name from row 2]
3. [Test name from row 3]
4. [Test name from row 4]
5. [Test name from row 5]

Last 5:
[N-4]. [Test name]
[N-3]. [Test name]
[N-2]. [Test name]
[N-1]. [Test name]
[N]. [Test name]

Return JSON:
{{
  "total_test_rows": 24,
  "report_language": "Arabic/English/Bilingual",
  "table_reading_direction": "Right-to-left" or "Left-to-right",
  "column_map": {{
    "test_name_column": "Rightmost column",
    "value_column": "Second from right",
    "unit_column": "Third from right",
    "range_column": "Leftmost column"
  }},
  "doctor_name_location": "Found at [location] or [exact text]",
  "lab_name_location": "Found at [location] or [exact text]",
  "first_5_test_names": ["Test 1 (English/Arabic)", "Test 2 (English/Arabic)", "Test 3 (English/Arabic)", "Test 4 (English/Arabic)", "Test 5 (English/Arabic)"],
  "last_5_test_names": ["Test 20 (English/Arabic)", "Test 21 (English/Arabic)", "Test 22 (English/Arabic)", "Test 23 (English/Arabic)", "Test 24 (English/Arabic)"],
  "patient_gender_value": "أنثى (=Female)" or "ذكر (=Male)",
  "extraction_instructions": "DETAILED step-by-step:
1. Patient name is at [exact location]
2. Gender field shows '[value]' which means [Male/Female]
3. Medical table starts at [location] with [total_test_rows] rows
4. For EACH of the [total_test_rows] rows:
   - Column [X]: Test name
   - Column [Y]: Result value  
   - Column [Z]: Unit
   - Column [W]: Normal range in format (X-Y) o
7. Extract doctor_names from [location found in analysis]
8. Extract lab_name or clinic_name if visibler (X-Y) mg/dL
5. Extract ALL [total_test_rows] rows sequentially from top to bottom
6. Do NOT skip any rows, even if value is empty"
}}

🚨 REMEMBER: If the table has 24 rows, you MUST report total_test_rows: 24, not 6!
"""


def get_custom_extraction_prompt(analysis, idx, total_pages):
    """Generate extraction prompt based on the analysis."""
    instructions = analysis.get('extraction_instructions', '')
    total_rows = analysis.get('total_test_rows', 20)
    column_map = analysis.get('column_map', {})
    first_5_tests = analysis.get('first_5_test_names', [])
    last_5_tests = analysis.get('last_5_test_names', [])
    
    return f"""🚨 EXTRACT ALL {total_rows} MEDICAL TEST ROWS 🚨

Page {idx}/{total_pages} - You ALREADY analyzed this report and found {total_rows} rows.

📋 YOUR ANALYSIS RESULTS:
- Total rows to extract: {total_rows}
- Language: {analysis.get('report_language', 'Unknown')}
- Table direction: {analysis.get('table_reading_direction', 'Unknown')}
- Column positions: {json.dumps(column_map, ensure_ascii=False)}
- First 5 test names you saw: {json.dumps(first_5_tests, ensure_ascii=False)}
- Last 5 test names you saw: {json.dumps(last_5_tests, ensure_ascii=False)}
- Doctor name location: {analysis.get('doctor_name_location', 'Not found')}
- Lab name location: {analysis.get('lab_name_location', 'Not found')}

🎯 CUSTOM EXTRACTION INSTRUCTIONS FOR THIS REPORT:
{instructions}

⚠️⚠️⚠️ CRITICAL REQUIREMENTS ⚠️⚠️⚠️
1. Extract EXACTLY {total_rows} items in medical_data array
2. Start from row 1 (first test: "{first_5_tests[0] if first_5_tests else 'see image'}") 
3. Continue through ALL rows until row {total_rows} (last test: "{last_5_tests[-1] if last_5_tests else 'see image'}")
4. For EACH row, even if a value is empty or blank:
   - Extract field_name (test name)
   - Extract field_value (result, write "N/A" if blank)
   - Extract field_unit (unit of measurement, "" if none)
   - Extract normal_range EXACTLY from image (format: "(X-Y)" or "(X-Y) unit")
   - Set is_normal: true/false/null based on comparison
5. Gender: Convert {analysis.get('patient_gender_value', 'ذكر/أنثى')} to English "Male" or "Female"
6. Normal ranges: Read from IMAGE, not from memory! If range says "(10-15)", write "(10-15)", NOT "(0-0.75)"!

🔍 CRITICAL EXTRACTION RULES:
1. For EACH field: extract test name EXACTLY as shown (preserve Arabic if Arabic, English if English)
2. Extract value ONLY if it exists in image - do NOT guess or invent
3. Extract normal range ONLY if shown in image - if empty/missing in image, leave as empty string ""
4. NEVER invent a normal range like "(0-0.75)" if not visible in image
5. Gender MUST be converted to English: "ذكر" -> "Male", "أنثى" -> "Female"
6. Patient name MUST be the actual person's name, not a label
7. Doctor name MUST be found and returned - look at signature area, header, or footer

🔍 ROW-BY-ROW EXTRACTION CHECKLIST:
As you extract, verify each row has all 4 pieces (or mark as empty if missing):
✓ Row 1: {first_5_tests[0] if first_5_tests else '[First test name]'} - value, unit, range (if exists)
✓ Row 2: {first_5_tests[1] if len(first_5_tests) > 1 else '[Second test name]'} - value, unit, range (if exists)
...
✓ Row {total_rows-2}: {last_5_tests[-3] if len(last_5_tests) > 2 else '[Third from last]'} - value, unit, range (if exists)
✓ Row {total_rows-1}: {last_5_tests[-2] if len(last_5_tests) > 1 else '[Second from last]'} - value, unit, range (if exists)  
✓ Row {total_rows}: {last_5_tests[-1] if last_5_tests else '[Last test name]'} - value, unit, range (if exists)

🔄 MULTI-PAGE REMINDER: You're analyzing page {idx}/{total_pages}. Extract ALL data from THIS page.

📦 FINAL VALIDATION BEFORE RETURNING:
❌ If medical_data.length < {total_rows}, you FAILED - go back and extract missing rows!
❌ If any normal_range looks like "(0-0.75)" but doesn't match image, you HALLUCINATED!
❌ If gender is "ذكر" or "أنثى", you FAILED to convert to English!
✅ Only return when you have ALL {total_rows} items with correct ranges!

Return JSON:Full patient name from image",
  "patient_age": "Age in years",
  "patient_dob": "Birth date YYYY-MM-DD",
  "patient_gender": "Male" or "Female",
  "report_date": "YYYY-MM-DD",EXACTLY from image (preserve language: Arabic or English)",
      "field_value": "Result value from image ONLY - if missing in image, put empty string",
      "field_unit": "Unit from image (e.g., mg/dl, %, cells/L) - if missing, put empty string",
      "normal_range": "EXACT range from image like (10-15) or (10-15) mg/dL - if NOT shown in image, put empty string (NOT null, NOT hallucinated value)
  "doctor_names": "",
  "medical_data": [
    // Array of {total_rows} objects:
    {{
      "field_name": "Test name from image",
      "field_value": "Result value from image or N/A",
      "field_unit": "Unit from image",
      "normal_range": "EXACT range from image like (10-15) or (10-15) mg/dL",
      "is_normal": true/false/null,
      "category": "Clinical Chemistry / Hematology / etc",
      "notes": ""
    }}
  ]
}}
"""
