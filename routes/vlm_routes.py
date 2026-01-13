from flask import request, Response, stream_with_context
from flask_restx import Namespace, Resource, reqparse
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timezone
import requests
import base64
import json
import hashlib
import os
import fitz  # PyMuPDF
from PIL import Image
import io
import re

from models import db, User, Report, ReportField, ReportFile, MedicalSynonym
from config import ollama_client, Config
from utils.medical_validator import validate_medical_data, MedicalValidator
from utils.medical_mappings import add_new_alias
from ollama import Client

# Create namespace
vlm_ns = Namespace('vlm', description='VLM and Report operations')

# Standardized Report Types
REPORT_TYPES = [
    "Complete Blood Count (CBC)",
    "Lipid Panel",
    "Comprehensive Metabolic Panel (CMP)",
    "Basic Metabolic Panel (BMP)",
    "Liver Function Test (LFT)",
    "Kidney Function Test (KFT)",
    "Thyroid Function Test (TFT)",
    "Hemoglobin A1C (HbA1c)",
    "Urinalysis",
    "Vitamin D Test",
    "Iron Studies",
    "Coagulation Panel (PT/INR/PTT)",
    "Cardiac Enzymes (Troponin)",
    "Electrolyte Panel",
    "Hormone Panel",
    "Tumor Markers",
    "Infectious Disease Test",
    "Allergy Test",
    "X-Ray",
    "CT Scan",
    "MRI Scan",
    "Ultrasound",
    "Mammogram",
    "DEXA Scan (Bone Density)",
    "ECG/EKG (Electrocardiogram)",
    "Echocardiogram",
    "Stress Test",
    "Pulmonary Function Test (PFT)",
    "Colonoscopy Report",
    "Endoscopy Report",
    "Biopsy Report",
    "Pathology Report",
    "Genetic Test",
    "COVID-19 Test",
    "Drug Screen/Toxicology",
    "General Medical Report",
    "Other"
]

# API Models for file upload
# Using reqparse for better Swagger file upload compatibility
upload_parser = reqparse.RequestParser()
upload_parser.add_argument('file', 
                          location='files',
                          type=FileStorage, 
                          required=True,
                          action='append',
                          help='Upload medical report image or PDF file. You can select multiple files at once.')


def allowed_file(filename):
    """Check if file has an allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def ensure_upload_folder(user_identifier):
    """Create user-specific upload folder if it doesn't exist"""
    user_folder = os.path.join(Config.UPLOAD_FOLDER, str(user_identifier))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder


def pdf_to_images(pdf_path):
    """Convert PDF to images using PyMuPDF with compression"""
    images = []
    pdf_document = fitz.open(pdf_path)
    
    for page_num in range(len(pdf_document)):
        page = pdf_document[page_num]
        # Render page to an image with 2.5x zoom (High quality ~180 DPI for better OCR)
        pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
        img_data = pix.tobytes("png")
        
        # Compress the image to reduce size
        img_data = compress_image(img_data, 'png')
        images.append(img_data)
    
    pdf_document.close()
    return images


def compress_image(image_data, format_hint='png'):
    """Compress image to reduce payload size while maintaining readability"""
    # Open image from bytes
    img = Image.open(io.BytesIO(image_data))
    
    # Convert RGBA to RGB if needed (for JPEG compatibility)
    if img.mode == 'RGBA':
        # Create white background
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])  # Use alpha channel as mask
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Resize if image is very large (3000px limit allows for ~250DPI on A4, better for OCR)
    max_dimension = 3000
    if max(img.size) > max_dimension:
        ratio = max_dimension / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        print(f"  ↓ Resized image to fit {max_dimension}px")
    
    # Compress to JPEG with quality 90 (High quality for text readability)
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=90, optimize=True)
    compressed_data = output.getvalue()
    
    original_size = len(image_data) / 1024  # KB
    compressed_size = len(compressed_data) / 1024  # KB
    reduction = ((original_size - compressed_size) / original_size * 100) if original_size > 0 else 0
    
    print(f"  📦 Compressed: {original_size:.1f}KB → {compressed_size:.1f}KB ({reduction:.1f}% reduction)")
    
    return compressed_data


@vlm_ns.route('/chat')
class ChatResource(Resource):
    @vlm_ns.doc(
        security='Bearer Auth',
        description='Stream real-time progress of medical report extraction using Server-Sent Events (SSE).',
        consumes=['multipart/form-data'],
        responses={
            200: 'Success - Stream started',
            400: 'Bad Request - Invalid file or missing data',
            404: 'User not found'
        }
    )
    @vlm_ns.expect(upload_parser)
    @jwt_required()
    def post(self):
        """Stream medical report extraction progress via SSE"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        if 'file' not in request.files:
            return {'error': 'No file part in the request. Please upload a file using form-data with key "file"', 'code': 'NO_FILE'}, 400
        
        files = request.files.getlist('file')
        profile_id = request.form.get('profile_id')
        
        print(f"DEBUG UPLOAD: User {current_user_id} attempting upload. Profile ID: {profile_id}")

        # Determine target profile
        target_profile_id = None
        if profile_id:
            from models import Profile
            prof = Profile.query.filter_by(id=profile_id, creator_id=current_user_id).first()
            
            if prof:
                print(f"DEBUG UPLOAD: User is OWNER of profile {profile_id}")
            
            # Check shared access if not owner
            if not prof:
                from models import ProfileShare
                share = ProfileShare.query.filter_by(
                    profile_id=profile_id, 
                    shared_with_user_id=current_user_id
                ).first()
                
                if share:
                    print(f"DEBUG UPLOAD: User has SHARED access. Level: {share.access_level}")
                    if share.access_level in ['upload', 'manage']:
                        prof = Profile.query.get(profile_id)
                    else:
                        print(f"DEBUG UPLOAD: Access DENIED. View-only user tried to upload.")
                        return {'error': 'Permission Denied: You only have view access to this profile. Uploading is not allowed.', 'code': 'ACCESS_DENIED'}, 403
            
            if not prof:
                print(f"DEBUG UPLOAD: Profile not found or no access.")
                return {'error': 'Invalid profile_id or unauthorized access (upload permission required)', 'code': 'UNAUTHORIZED'}, 403
            target_profile_id = prof.id
        else:
            # Default to 'Self' profile
            from models import Profile
            prof = Profile.query.filter_by(creator_id=current_user_id, relationship='Self').first()
            if prof:
                target_profile_id = prof.id
        
        if not files or len(files) == 0:
            return {'error': 'No file selected'}, 400

        # Pre-check for duplicates to return 409 Conflict immediately
        # This prevents returning a 200 OK stream that immediately fails
        for file in files:
            if file.filename == '': continue
            
            # Read and hash to check for duplicates
            # Note: We must seek(0) after reading to ensure the file can be read again later
            try:
                file_content = file.read()
                file_hash = hashlib.sha256(file_content).hexdigest()
                file.seek(0) # CRITICAL: Reset cursor
                
                existing_file = ReportFile.query.filter_by(user_id=current_user_id, file_hash=file_hash).first()
                if existing_file:
                    return {
                        'error': f'Duplicate detected: The file "{file.filename}" has already been processed (Report #{existing_file.report_id})',
                        'code': 'DUPLICATE_FILE',
                        'report_id': existing_file.report_id
                    }, 409
            except Exception as e:
                print(f"Pre-check error: {e}")
                file.seek(0) # Ensure reset even on error

        # Create user-specific folder
        user_folder = ensure_upload_folder(f"user_{current_user_id}")
        
        # Generator for streaming response
        def generate_progress():
            try:
                yield f"data: {json.dumps({'percent': 2, 'message': 'Preparing your file for analysis...'})}\n\n"
                
                all_images_to_process = []
                saved_files = []
                
                # Pre-processing loop
                total_files = len(files)
                for i, file in enumerate(files):
                    if file.filename == '': continue
                    
                    yield f"data: {json.dumps({'percent': 5 + int((i/total_files)*15), 'message': f'Wait a second, Optimizing file {i+1} of {total_files}...'})}\n\n"
                    
                    # 1. Calculate File Hash for Duplicate Detection
                    file_content = file.read()
                    file_hash = hashlib.sha256(file_content).hexdigest()
                    file.seek(0)
                    
                    # Check for duplicate FILE
                    existing_file = ReportFile.query.filter_by(user_id=current_user_id, file_hash=file_hash).first()
                    if existing_file:
                        error_msg = f'Duplicate detected: The file "{file.filename}" has already been processed (Report #{existing_file.report_id})'
                        yield f"data: {json.dumps({'error': error_msg, 'code': 'DUPLICATE_FILE', 'report_id': existing_file.report_id})}\n\n"
                        return

                    # Save file
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    unique_filename = f"{timestamp}_{filename}"
                    file_path = os.path.join(user_folder, unique_filename)
                    file.save(file_path)
                    
                    file_size = os.path.getsize(file_path)
                    file_extension = filename.rsplit('.', 1)[1].lower()
                    
                    saved_files.append({
                        'original_filename': filename,
                        'stored_filename': unique_filename,
                        'file_path': file_path,
                        'file_type': file_extension,
                        'file_size': file_size,
                        'file_hash': file_hash,
                        'is_pdf': file_extension == 'pdf'
                    })
                    
                    if file_extension == 'pdf':
                        yield f"data: {json.dumps({'percent': 15, 'message': f'Scanning your document pages...'})}\n\n"
                        images = pdf_to_images(file_path)
                        for page_num, img_data in enumerate(images, 1):
                            all_images_to_process.append({
                                'data': img_data,
                                'format': 'jpeg',
                                'source_filename': filename,
                                'page_number': page_num,
                                'total_pages': len(images)
                            })
                    else:
                        with open(file_path, 'rb') as f:
                            image_data = f.read()
                            compressed_data = compress_image(image_data, file_extension)
                            all_images_to_process.append({
                                'data': compressed_data,
                                'format': 'jpeg',
                                'source_filename': filename,
                                'page_number': None,
                                'total_pages': 1
                            })
                
                if not all_images_to_process:
                    yield f"data: {json.dumps({'error': 'No valid image data to process'})}\n\n"
                    return

                # Process Images Generator
                yield from self._process_multiple_images_stream(all_images_to_process, current_user_id, user, saved_files, target_profile_id)
                
            except Exception as e:
                print(f"Stream Error: {e}")
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'error': f'Server Error: {str(e)}'})}\n\n"

        return Response(stream_with_context(generate_progress()), content_type='text/event-stream')

    def _process_multiple_images_stream(self, images_list, current_user_id, user, saved_files, profile_id=None):
        """Generator that yields progress for image processing steps"""
        total_pages = len(images_list)
        all_extracted_data = []
        patient_info = {}
        
        yield f"data: {json.dumps({'percent': 20, 'message': f'Analyzing your medical report...'})}\n\n"
        
        print(f"\n{'='*80}")
        print(f"🔄 STREAMING PROCESS STARTED: {total_pages} page(s)")
        print(f"{'='*80}")
        
        for idx, image_info in enumerate(images_list, 1):
            # Progress calculation: 20% -> 70%
            current_progress = 20 + int((idx / total_pages) * 50)
            
            print(f"\n{'='*80}")
            print(f"📄 Processing Page {idx}/{total_pages} ({int((idx-1)/total_pages*100)}% complete)")
            print(f"📁 File: {image_info['source_filename']}")
            if image_info.get('page_number'):
                print(f"📖 PDF Page: {image_info['page_number']}/{image_info.get('total_pages', '?')}")
            print(f"{'='*80}\n")
            
            # Step 1: VLM Processing (Native Vision)
            print(f"🤖 Step 1: Structuring data with Qwen2-VL (native vision)...")
            yield f"data: {json.dumps({'percent': current_progress + 10, 'message': f'Extracting medical values from page {idx}...'})}\n\n"
            
            # Build prompt (Reusing logic)
            # Build OPTIMIZED extraction prompt (reduced by ~40%)
            prompt_text = f"""Analyze this image (page {idx}/{total_pages}) and determine if it is a medical report.

CRITICAL CHECK:
- If this image is CLEARLY NOT a medical document (e.g., selfie, landscape, car, receipt, blank page, animal), return ONLY:
  {{ "is_medical_report": false, "reason": "Not a medical report" }}
- If it IS a medical report, extract data using these rules:

You are analyzing a medical laboratory report. Your previous extraction had CRITICAL ERRORS. Fix them by following these EXACT rules:

## CRITICAL FIXES NEEDED:

### Issue #1: "Test Name" in field_name
**WRONG:** {{"field_name": "Test Name", "field_value": "Creatinine, serum"}}
**CORRECT:** {{"field_name": "Creatinine, serum", "field_value": "0.85"}}

- The TEST NAME goes in "field_name"
- The NUMERIC RESULT or qualitative result (like "Negative") goes in "field_value"
- NEVER put "Test Name" as the field_name value

### Issue #2: Row Alignment Errors
**CRITICAL TABLE READING RULES:**

1. **Identify Table Structure First:**
   - Find the column headers: "Test Name", "Result", "Unit", "Normal Range"
   - Determine if it's LTR (Left-to-Right) or RTL (Right-to-Left)

2. **For Each Row:**
   - Lock onto the test name FIRST
   - Move HORIZONTALLY on the SAME LINE to find:
     - Result value (number or text)
     - Unit (mg/dL, %, g/dL, etc.)
     - Normal range
   
3. **Common Mistakes to AVOID:**
   - ❌ Taking a value from the row above or below
   - ❌ Mixing values between "Monocytes %" and "Monocytes" (absolute count)
   - ❌ Assigning the same value to multiple tests
   - ❌ Reading diagonally instead of horizontally

### Issue #3: Units Must Match the Test Type

**Common test patterns:**
- **CBC components:**
  - WBC, RBC, Platelets → usually "10^9/L" or "K/uL" or "cells/L"
  - Hemoglobin → "g/dL"
  - Hematocrit → "%"
  - MCV → "fL"
  - MCH → "pg"
  - MCHC → "g/dL" or "%"
  
- **Differential counts:**
  - Neutrophils %, Lymphocytes %, Monocytes % → "%"
  - Neutrophils (absolute), Lymphocytes (absolute) → "10^9/L" or "K/uL"

- **Chemistry:**
  - Glucose, Creatinine, Urea, Cholesterol → "mg/dL" or "mmol/L"
  - ALT, AST → "U/L" or "IU/L"

**VERIFY:** If the unit seems wrong for the test type, recheck the column alignment.

### Issue #4: is_normal Flag Logic
```python
# Your logic should be:
value = float(field_value)
range_parts = normal_range.split('-')
min_val = float(range_parts[0])
max_val = float(range_parts[1])

is_normal = min_val <= value <= max_val
```

**Current errors:**
- Monocytes % 14.4 with range 3-7 → Should be HIGH (is_normal: false), but you marked it as Low
- Always check: value BELOW range = Low, value ABOVE range = High

### Issue #5: Handling Flags and Markers

If you see asterisks (*), L, H, or arrows (↑↓):
- Extract ONLY the number in "field_value"
- Put "Marked as High on report" or "Marked as Low on report" in "notes"
- Set is_normal based on actual comparison, not just the flag

---

### Issue #6: Test Name Validation
**Real vs Fake Test Names:**

❌ WRONG:
- "White blood cells%" → Not a standard test
- "Test Name" → Placeholder, not extracted

✅ CORRECT:
- "White blood cells (WBC)" → Absolute count
- "Neutrophils %" → Percentage 
- "Neutrophils (Absolute)" → Absolute count
- "Red blood cells (RBC)" → Absolute count

**If you see unusual test names, recheck the image.**

---

## Step-by-Step Extraction Process:

**STEP 1:** Look at the image and count total rows in the table (excluding header)

**STEP 2:** For EACH row, read strictly left-to-right or right-to-left:
Row 1: [Test Name] | [Value] | [Unit] | [Range]
↓              ↓         ↓        ↓
field_name    field_value  field_unit  normal_range

**STEP 3:** Double-check alignment by asking:
- "Is this value directly next to this test name on the same horizontal line?"
- "Does this unit make sense for this test type?"
- "Have I already used this value for another test?"

**STEP 4:** Validate completeness:
- Count extracted tests vs. visible rows
- Verify no "Test Name" appears in field_name
- Verify all field_value entries are numbers or qualitative terms (never test names)

**STEP 5: CATEGORY EXTRACTION (REQUIRED)**
- Look for section headers like "HEMATOLOGY", "BIOCHEMISTRY", "LIPID PROFILE".
- Assign the current header to all tests below it until a new header appears.
- Example: "category": "HEMATOLOGY"

---

## INSTRUCTIONS FOR PATIENT & REPORT INFO:

1. **Patient Name (CRITICAL):**
   - Extract the FULL patient name exactly as written.
   - SUPPORT ARABIC NAMES if present.
   - Look for "اسم المريض" (Patient Name) and extract the text next to it.
   - **CRITICAL:** EXCLUDE labels such as "Name:", "Patient Name:", "Patient:", "اسم", "المريض" from the extracted value.
   - **ACCURACY:** Copy the text EXACTLY as it appears in the image. Do NOT invent names.

2. **Report Details:**
   - Extract `report_date` (YYYY-MM-DD).
   - Extract `doctor_names` (Look for "Dr", "Doctor", "الطبيب").
   - Extract `patient_age` and `patient_gender`.
   - **Gender:** "ذكر" = Male, "أنثى" = Female.
   - **AGE CALCULATION (MANDATORY):**
     - If age is written as a date (e.g., "01/05/1975"), CALCULATE the age.
     - Formula: Age = Report Year - Birth Year.
     - Return ONLY the number (e.g., "50").

---

## FINAL CHECKLIST Before Returning JSON:

- [ ] Every field_name contains an actual test name (never "Test Name")
- [ ] Every field_value contains a number or qualitative result (never a test name)
- [ ] No duplicate values across different tests unless truly identical
- [ ] Units match the test type (% for percentages, proper units for counts)
- [ ] is_normal correctly reflects whether value is within range
- [ ] Total count matches visible rows in table

Return ONLY valid JSON:
{{
    "patient_name": "...",
    "patient_age": "...",
    "patient_gender": "...",
    "report_date": "YYYY-MM-DD",
    "report_name": "...",
    "report_type": "...",
    "doctor_names": "...",
    "is_medical_report": true,
    "total_fields_in_image": <count>,
    "medical_data": [
        {{
            "field_name": "Test Name",
            "field_value": "123.45 OR 'Normal'",
            "field_unit": "g/dL or empty",
            "normal_range": "13.5-17.5 or empty",
            "is_normal": true,
            "field_type": "measurement",
            "category": "DIFFERENTIAL COUNT or empty",
            "notes": "Marked as Low on report OR empty"
        }}
    ]
}}"""
            try:
                image_base64 = base64.b64encode(image_info['data']).decode('utf-8')
                image_format = image_info['format']
                
                content = [
                    {'type': 'text', 'text': prompt_text},
                    {
                        'type': 'image_url',
                        'image_url': {'url': f'data:image/{image_format};base64,{image_base64}'}
                    }
                ]
                
                completion = ollama_client.chat.completions.create(
                    model=Config.OLLAMA_MODEL,
                    messages=[{'role': 'user', 'content': content}],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )
                response_text = completion.choices[0].message.content.strip()
                print(f"🔍 RAW RESPONSE for Image {idx}:\n{'-'*40}\n{response_text[:300]}...\n{'-'*40}")
                
                # Parsing logic
                extracted_data = {}
                try:
                    import re
                    # Try to find the largest outer JSON object
                    start_idx = response_text.find('{')
                    end_idx = response_text.rfind('}')
                    
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        json_str = response_text[start_idx:end_idx+1]
                        extracted_data = json.loads(json_str)
                        print(f"✅ JSON extracted for Image {idx}")
                    else:
                        print(f"⚠️ No JSON brackets found in response for Image {idx}")
                        print(f"RAW: {response_text[:200]}...")
                except Exception as json_err:
                    print(f"⚠️ JSON Parsing Failed for Image {idx}: {json_err}")
                    print(f"RAW RESPONSE: {response_text}")
                
                # Check for Non-Medical Report Flag
                if extracted_data.get('is_medical_report') is False:
                     error_msg = extracted_data.get('reason', 'The uploaded file does not appear to be a valid medical report.')
                     print(f"⛔ Rejected as non-medical: {error_msg}")
                     # yield f"data: {json.dumps({'error': error_msg, 'code': 'INVALID_DOCUMENT_TYPE'})}\n\n"
                     # SKIP this page instead of aborting the whole process
                     continue
                
                if extracted_data.get('medical_data'):
                    new_items = extracted_data['medical_data']
                    
                    # --- DUPLICATE PREVENTION LOGIC ---
                    unique_new_items = []
                    existing_test_names = {item['field_name'].lower() for item in all_extracted_data}
                    
                    for item in new_items:
                        test_name = item.get('field_name', '').strip()
                        test_val = item.get('field_value', '').strip()
                        
                        # Skip empty or placeholder items
                        if not test_name or test_name.lower() == 'test name':
                            continue
                            
                        # Check for exact name match
                        if test_name.lower() in existing_test_names:
                            print(f"⚠️ Duplicate test skipped: {test_name}")
                            continue
                            
                        # Basic Validation
                        if not test_val or test_val.lower() in ['n/a', 'unknown']:
                             continue
                             
                        unique_new_items.append(item)
                        existing_test_names.add(test_name.lower())
                    
                    all_extracted_data.extend(unique_new_items)
                    print(f"✅ Extracted {len(unique_new_items)} UNIQUE field(s) from page {idx}")
                
                # Capture patient info (prefer the most complete one)
                new_name = extracted_data.get('patient_name', '')
                current_name = patient_info.get('patient_name', '')
                if len(new_name) > len(current_name):
                     patient_info = extracted_data

                print(f"✅ Page {idx} Analysis Complete. Found {len(extracted_data.get('medical_data', []))} data points.")
                     
            except Exception as e:
                print(f"❌ VLM Error on page {idx}: {e}")

        # Check if we have ANY data after processing all pages
        if not all_extracted_data:
             error_msg = 'No valid medical data found in any of the uploaded images.'
             yield f"data: {json.dumps({'error': error_msg, 'code': 'NO_DATA_FOUND'})}\n\n"
             return

        # Step 3: Validation
        yield f"data: {json.dumps({'percent': 75, 'message': 'Double-checking the results...'})}\n\n"
        print(f"🔍 Validating aggregated data ({len(all_extracted_data)} total items)...")
        
        # Clean Patient Name
        raw_name = patient_info.get('patient_name', '')
        cleaned_name = raw_name
        if cleaned_name:
            # Remove labels like "Patient Name:", "Name:", "Mr." at start
            # Added more patterns to catch "Name : John Doe" or "Patient: John Doe"
            cleaned_name = re.sub(r'^(Name|Patient Name|Patient|Mr\.?|Mrs\.?|Ms\.?|Dr\.?)\s*[:\-\.]?\s*', '', cleaned_name, flags=re.IGNORECASE)
            # Remove trailing noise like "Age:...", "Sex:...", "ID:...", "Date:..."
            cleaned_name = re.sub(r'\s+(Age|Sex|Gender|ID|Date|Ref|Dr)\s*[:\-\.].*$', '', cleaned_name, flags=re.IGNORECASE)
            cleaned_name = cleaned_name.strip()

        # Combine data
        final_data = {
            'patient_name': cleaned_name,
            'patient_age': patient_info.get('patient_age', ''),
            'patient_gender': patient_info.get('patient_gender', ''),
            'report_date': patient_info.get('report_date', ''),
            'report_name': patient_info.get('report_name', 'Medical Report'),
            'report_type': patient_info.get('report_type', 'General'),
            'doctor_names': patient_info.get('doctor_names', ''),
            'medical_data': all_extracted_data
        }
        
        # Validation Logic (Call utils)
        try:
            # ---------------------------------------------------------
            # AUTO-LEARNING SYNONYM STANDARDIZATION
            # ---------------------------------------------------------
            yield f"data: {json.dumps({'percent': 80, 'message': 'Standardizing and learning field names...'})}\n\n"
            print("🧠 Standardizing and learning field names...")
            
            # Create a modifiable list for synonym processing
            medical_data_list = final_data.get('medical_data', [])
            unknown_terms = []
            
            # 1. First Pass: check DB for existing synonyms
            for item in medical_data_list:
                original_name = item.get('field_name', '').strip()
                if not original_name or len(original_name) < 2:
                    continue
                    
                synonym_record = MedicalSynonym.query.filter_by(synonym=original_name.lower()).first()
                if synonym_record:
                    # Known alias -> Use standard name (KEEP ORIGINAL NAME as requested)
                    print(f"   ✓ Recognized: '{original_name}' (Standard: '{synonym_record.standard_name}')")
                    # item['field_name'] = synonym_record.standard_name  <-- KEEP ORIGINAL NAME
                else:
                    # Unknown -> Queue for batch learning
                    if original_name not in unknown_terms:
                        unknown_terms.append(original_name)
            
            # 2. Batch Processing for Unknown Terms
            if unknown_terms:
                print(f"   ❓ Found {len(unknown_terms)} unknown terms. Asking AI in BATCH mode...")
                try:
                    terms_list_str = json.dumps(unknown_terms)
                    learning_prompt = f"""Identify the standard medical name for these tests: {terms_list_str}.
                    Return a JSON object mapping each original name to its standard name.
                    Example format: {{"original_name1": "Standard Name 1", "original_name2": "Standard Name 2"}}
                    If a term is already standard, map it to itself.
                    If not a valid medical test, map to "UNKNOWN".
                    Return ONLY the JSON."""
                    
                    # Using the larger model as requested by user, but batched for speed
                    # Use the existing OpenAI-compatible client to avoid URL/Proxy issues
                    response = ollama_client.chat.completions.create(
                        model='gemma3:12b', 
                        messages=[
                            {'role': 'user', 'content': learning_prompt}
                        ]
                    )
                    
                    response_text = response.choices[0].message.content.strip()
                    # Clean markdown code blocks if present
                    if "```json" in response_text:
                        response_text = response_text.split("```json")[1].split("```")[0].strip()
                    elif "```" in response_text:
                        response_text = response_text.split("```")[1].split("```")[0].strip()
                        
                    learned_map = json.loads(response_text)
                    
                    # 3. Process learned terms
                    for original, standardized in learned_map.items():
                        standardized = standardized.strip()
                        if standardized and standardized != 'UNKNOWN' and len(standardized) < 50:
                            # Learn it (save to DB)
                            if standardized.lower() != original.lower():
                                print(f"   💡 Learned: '{original}' is alias for '{standardized}'")
                                add_new_alias(original, standardized)
                                # Also ensure standard name is in DB as a self-mapping
                                add_new_alias(standardized, standardized)
                            else:
                                print(f"   📝 registered new standard term: '{standardized}'")
                                add_new_alias(standardized, standardized)
                                
                            # Update items in the list (KEEP ORIGINAL NAME as requested)
                            # for item in medical_data_list:
                            #     if item.get('field_name') == original:
                            #         item['field_name'] = standardized
                                    
                except Exception as learn_err:
                    print(f"   ⚠️ Batch learning failed: {learn_err}")

            # Update final_data with standardized list
            final_data['medical_data'] = medical_data_list

            # Apply medical validator for 100% accuracy
            validated_data = validate_medical_data(final_data)
            
            original_count = len(final_data.get('medical_data', []))
            validated_count = len(validated_data.get('medical_data', []))
            
            print(f"✅ Validation complete!")
            print(f"   - Original fields: {original_count}")
            print(f"   - After deduplication: {validated_count}")
            
            final_data = validated_data
        except Exception as e:
            print(f"Validation Error: {e}")
            import traceback
            traceback.print_exc()

        # Parse extracted report date (YYYY-MM-DD), fallback to now()
        # Moved before Duplicate Check to allow semantic date matching
        report_date_obj = datetime.now(timezone.utc)
        extracted_date = final_data.get('report_date')
        date_is_valid = False
        
        if extracted_date and len(extracted_date) >= 10:
            try:
                # Parse YYYY-MM-DD
                report_date_obj = datetime.strptime(extracted_date[:10], '%Y-%m-%d')
                date_is_valid = True
            except:
                print(f"⚠️ Could not parse report date: {extracted_date}, using now()")

        # Step 4: Duplicate Check (Semantic & Exact)
        yield f"data: {json.dumps({'percent': 85, 'message': 'Checking for duplicates...'})}\n\n"
        
        try:
            medical_data_list = final_data.get('medical_data', [])
            if len(medical_data_list) > 0:
                # 1. Strict Hash Check (Fastest)
                report_hash = hashlib.sha256(json.dumps(medical_data_list, sort_keys=True).encode()).hexdigest()
                
                # Check if this exact report already exists for this user
                existing_report = Report.query.filter_by(
                    user_id=current_user_id,
                    report_hash=report_hash
                ).first()
                
                # 2. Semantic Check (Content Similarity)
                # Handles cases like PDF vs Images where hash differs but content is identical
                if not existing_report and date_is_valid:
                    # Look for reports on the SAME DATE by this user
                    candidates = Report.query.filter(
                        Report.user_id == current_user_id,
                        Report.report_date == report_date_obj
                    ).all()
                    
                    if candidates:
                        print(f"🔍 Found {len(candidates)} reports on {report_date_obj.date()}. Checking content similarity...")
                        
                        # Prepare current report set {(name_norm, value_norm)}
                        current_set = set()
                        for item in medical_data_list:
                            n = item.get('field_name', '').strip().lower()
                            v = str(item.get('field_value', '')).strip().lower()
                            if n and v:
                                current_set.add((n, v))
                        
                        if len(current_set) > 0:
                            for cand in candidates:
                                # Fetch candidate fields
                                cand_fields = ReportField.query.filter_by(report_id=cand.id).all()
                                cand_set = set()
                                for f in cand_fields:
                                    n = f.field_name.strip().lower()
                                    v = f.field_value.strip().lower()
                                    cand_set.add((n, v))
                                
                                # Calculate Overlap
                                intersection = current_set.intersection(cand_set)
                                overlap_ratio = len(intersection) / len(current_set) if len(current_set) > 0 else 0
                                
                                print(f"   - Candidate #{cand.id}: {len(intersection)}/{len(current_set)} matches ({overlap_ratio:.2f})")
                                
                                # Threshold: if > 75% of extracted fields match -> DUPLICATE
                                if overlap_ratio > 0.75:
                                    existing_report = cand
                                    print(f"❌ DETECTED SEMANTIC DUPLICATE of Report #{cand.id}")
                                    break

                if existing_report:
                    error_msg = f'Duplicate Detected: This report content matches an existing report (#{existing_report.id}) from {existing_report.report_date.strftime("%Y-%m-%d")}'
                    yield f"data: {json.dumps({'error': error_msg, 'code': 'DUPLICATE_REPORT', 'report_id': existing_report.id})}\n\n"
                    return
                
        except Exception as e:
             print(f"Duplicate Check Error: {e}")

        # Step 5: Saving
        yield f"data: {json.dumps({'percent': 90, 'message': 'Saving your report...'})}\n\n"
        print(f"💾 Saving report to database...")
        
        new_report_id = None
        try:
            # Calculate report hash
            report_hash = hashlib.sha256(json.dumps(final_data['medical_data'], sort_keys=True).encode()).hexdigest()
            
            # report_date_obj is already parsed above

            # Categorize report
            from utils.medical_mappings import categorize_report_type
            report_category = categorize_report_type(final_data.get('report_type'))

            new_report = Report(
                user_id=current_user_id,
                profile_id=profile_id,
                report_date=report_date_obj,
                report_hash=report_hash,
                report_name=final_data.get('report_name'),
                report_type=final_data.get('report_type'),
                report_category=report_category,
                patient_name=final_data.get('patient_name'),
                patient_age=final_data.get('patient_age'),
                patient_gender=final_data.get('patient_gender'),
                doctor_names=final_data.get('doctor_names'),
                original_filename=saved_files[0]['original_filename'] if saved_files else "unknown"
            )
            db.session.add(new_report)
            db.session.flush()
            new_report_id = new_report.id
            
            # Save files
            for f in saved_files:
                rf = ReportFile(report_id=new_report.id, user_id=current_user_id, **{k:v for k,v in f.items() if k!='is_pdf'})
                if f['is_pdf']:
                     # Find associated pages for PDF
                     pdf_pages = [img for img in images_list if img['source_filename'] == f['original_filename']]
                     for p in pdf_pages:
                         rf_page = ReportFile(
                             report_id=new_report.id, user_id=current_user_id, 
                             original_filename=f['original_filename'], stored_filename=f['stored_filename'],
                             file_path=f['file_path'], file_type=f['file_type'], file_size=f['file_size'],
                             file_hash=f['file_hash'], page_number=p.get('page_number')
                         )
                         db.session.add(rf_page)
                else:
                    db.session.add(rf)
                
            # Save fields
            medical_entries = []
            for item in final_data['medical_data']:
                if isinstance(item, dict):
                    field = ReportField(
                        report_id=new_report.id,
                        user_id=current_user_id,
                        field_name=item.get('field_name', 'Unknown'),
                        field_value=str(item.get('field_value', '')),
                        field_unit=str(item.get('field_unit', '')),
                        normal_range=str(item.get('normal_range', '')),
                        is_normal=bool(item.get('is_normal', True)),
                        field_type=str(item.get('field_type', 'measurement')),
                        category=str(item.get('category', '')),
                        notes=str(item.get('notes', ''))
                    )
                    db.session.add(field)
                    db.session.flush()
                    
                    medical_entries.append({
                        'id': field.id,
                        'field_name': field.field_name,
                        'field_value': field.field_value,
                        'is_normal': field.is_normal
                    })
            
            db.session.commit()
            
            # Send Notifications
            try:
                from utils.notification_service import notify_report_upload
                from models import ProfileShare, Profile
                
                # Get profile details
                profile = Profile.query.get(profile_id)
                if profile:
                    recipients = set()
                    
                    # Add owner if not current user
                    if profile.creator_id != current_user_id:
                        recipients.add(profile.creator_id)
                        
                    # Add shared users
                    shares = ProfileShare.query.filter_by(profile_id=profile_id).all()
                    for share in shares:
                        if share.shared_with_user_id != current_user_id:
                            recipients.add(share.shared_with_user_id)
                    
                    if recipients:
                        uploader = User.query.get(current_user_id)
                        uploader_name = f"{uploader.first_name} {uploader.last_name or ''}".strip()
                        profile_name = f"{profile.first_name} {profile.last_name or ''}".strip()
                        report_name = new_report.report_name or "Medical Report"
                        
                        notify_report_upload(uploader_name, profile_name, report_name, list(recipients), profile_id, new_report.id)
            except Exception as e:
                print(f"Notification failed: {e}")
            
            # Final Success Payload - Keep it small efficiently
            success_payload = {
                'percent': 100, 
                'message': 'Analysis Completed!', 
                'report_id': new_report.id
            }
            print(f"✅ SUCCESS: Report #{new_report.id} created with {len(medical_entries)} fields.")
            yield f"data: {json.dumps(success_payload)}\n\n"
            
        except Exception as e:
            db.session.rollback()
            yield f"data: {json.dumps({'error': f'❌ Database Error: {str(e)}'})}\n\n"
