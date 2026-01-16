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
    """Convert PDF pages to images using PyMuPDF with light compression for VLM"""
    images = []
    pdf_document = fitz.open(pdf_path)
    
    for page_num in range(len(pdf_document)):
        page = pdf_document[page_num]
        # Render page to an image with 2.5x zoom (High quality ~180 DPI for better OCR)
        pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
        img_data = pix.tobytes("png")
        # Compress copy for VLM (original PDF stays unchanged on disk)
        compressed = compress_image(img_data, 'png')
        images.append(compressed)
    
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
    
    # Resize if image is very large (limit dimensions to keep VLM fast but text readable)
    max_dimension = 2000
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
        allow_duplicate_flag = request.form.get('allow_duplicate', 'false')
        allow_duplicate = str(allow_duplicate_flag).lower() == 'true'
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

        if not allow_duplicate:
            for file in files:
                if file.filename == '': 
                    continue
                
                try:
                    file_content = file.read()
                    file_hash = hashlib.sha256(file_content).hexdigest()
                    file.seek(0)

                    existing_file = None
                    if target_profile_id:
                        existing_file = db.session.query(ReportFile).join(Report, ReportFile.report_id == Report.id).filter(
                            ReportFile.file_hash == file_hash,
                            Report.profile_id == target_profile_id
                        ).first()
                    else:
                        existing_file = ReportFile.query.filter_by(user_id=current_user_id, file_hash=file_hash).first()

                    if existing_file:
                        return {
                            'error': f'Duplicate detected: The file "{file.filename}" has already been processed (Report #{existing_file.report_id})',
                            'code': 'DUPLICATE_FILE',
                            'report_id': existing_file.report_id
                        }, 409
                except Exception as e:
                    print(f"Pre-check error: {e}")
                    file.seek(0)

        # Create user-specific folder
        user_folder = ensure_upload_folder(f"user_{current_user_id}")
        
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
                    
                    file_content = file.read()
                    file_hash = hashlib.sha256(file_content).hexdigest()
                    file.seek(0)
                    
                    if not allow_duplicate:
                        existing_file = None
                        if profile_id:
                            existing_file = db.session.query(ReportFile).join(Report, ReportFile.report_id == Report.id).filter(
                                ReportFile.file_hash == file_hash,
                                Report.profile_id == profile_id
                            ).first()
                        else:
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
                            # Compress copy for VLM (stored file remains original)
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

                yield from self._process_multiple_images_stream(all_images_to_process, current_user_id, user, saved_files, target_profile_id, allow_duplicate)
                
            except Exception as e:
                print(f"Stream Error: {e}")
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'error': f'Server Error: {str(e)}'})}\n\n"

        return Response(stream_with_context(generate_progress()), content_type='text/event-stream')

    def _process_multiple_images_stream(self, images_list, current_user_id, user, saved_files, profile_id=None, allow_duplicate=False):
        """Generator that yields progress for image processing steps"""
        total_pages = len(images_list)
        all_extracted_data = []
        patient_info = {}
        report_owner_id = current_user_id
        if profile_id:
            from models import Profile
            profile = Profile.query.get(profile_id)
            if profile:
                report_owner_id = profile.creator_id
        
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
            
            prompt_text = f"""You are an expert medical data digitizer.

You receive a medical report IMAGE (page {idx}/{total_pages}). The report may be:
- Arabic, English, or mixed
- Printed, scanned, rotated, or low quality
- With header tables, main tables, lines, or free text

Your job is to read the WHOLE image carefully and return a single JSON object with strictly correct values.

GENERAL RULES:
- Always read values exactly from the report; never guess or correct.
- If a field is missing, blurred, or not clearly present, return an empty string "" for it.
- Never invent a name, date, gender, age, doctor, or result.
- If multiple candidates exist, choose the one closest to the main patient header.
- Do not copy label words as values (for example: "اسم المريض", "Patient Name").
- CRITICAL: Each test result row is independent. NEVER mix values from different rows or columns.

STEP 1: PATIENT HEADER READING
Scan all regions (right/left, top/bottom) carefully. Look for header tables or sections.
Handle both Arabic and English labels. Read each label-value pair precisely:

- Patient Name labels:
  - Arabic: "اسم المريض", "المريض", "الاسم"
  - English: "Patient Name", "Name", "Patient"
  -> Extract ONLY the actual name. Remove any labels or prefixes like "Name:", "Patient Name:".
  -> Return the full name as written (Arabic or English).
  -> If name contains extra text like "Patient Name: John Doe", extract only "John Doe".
  -> If not found, return "".

- Gender labels:
  - Arabic: "الجنس", "الجنسي"
  - English: "Sex", "Gender"
  -> Return "Male" if you see: "ذكر", "Male", "M", "ذكر" in Arabic
  -> Return "Female" if you see: "أنثى", "انثى", "Female", "F", "أنثى" in Arabic
  -> If not found or unclear, return "".
  -> Do NOT infer gender from names.

- Date of Birth / Age labels:
  - Arabic: "تاريخ الميلاد", "عمر", "العمر"
  - English: "DOB", "Date of Birth", "Birth Date", "Age"
  -> If DATE OF BIRTH is found, extract and normalize to "YYYY-MM-DD" format.
  -> If only AGE is found (e.g., "50 years", "50 Y", "50"), extract the number only (e.g., "50").
  -> If both are found, prefer date of birth for patient_dob and calculate/use age for patient_age.
  -> Date formats to recognize: DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD, DD-MM-YYYY
  -> If not found, return "" for both.

- Report Date labels:
  - Arabic: "تاريخ الطلب", "التاريخ", "تاريخ الفحص"
  - English: "Report Date", "Date", "Test Date"
  -> Normalize to "YYYY-MM-DD" format when possible.
  -> If not found, return "".

- Doctor labels:
  - Arabic: "الطبيب", "طبيب"
  - English: "Doctor", "Physician", "Ref By", "Referred By"
  -> Extract only the doctor name(s), without prefixes like "Dr.", "Doctor:".
  -> If multiple doctors, separate with commas.
  -> If not found, return "".

STEP 2: SPECIAL CASE – HEADER TABLES (Palestinian/Arabic Lab Forms)
Many reports have two side-by-side header tables:
- RIGHT table: Patient information (Arabic labels like "رقم المريض", "اسم المريض", "الجنس", "تاريخ الميلاد", "رقم الهوية")
- LEFT table: Request information (Arabic labels like "تاريخ الطلب", "رقم الطلب", "الطبيب")

READ CAREFULLY:
- Each row has: LABEL in one cell, VALUE in adjacent cell.
- Match each label to its correct value in the SAME row.
- Do NOT mix values from different rows.
- Extract patient_name from the row with "اسم المريض" label.
- Extract patient_gender from the row with "الجنس" label.
- Extract patient_dob or patient_age from "تاريخ الميلاد" or "عمر" row.

STEP 3: LAB TABLE EXTRACTION (CRITICAL - NO MIXING VALUES!)
Extract test results from tables. Each ROW is one test. NEVER mix values between rows.

Map column headers:
- Arabic: "الفحص"/"الاختبار" -> field_name
- Arabic: "النتيجة"/"القيمة" -> field_value  
- Arabic: "الوحدة" -> field_unit
- Arabic: "المعدل الطبيعي"/"النتيجة الطبيعية" -> normal_range
- English: "Test"/"Examination" -> field_name
- English: "Result"/"Value" -> field_value
- English: "Unit" -> field_unit
- English: "Normal Range"/"Reference Range" -> normal_range

ROW-BY-ROW EXTRACTION RULES:
1. For EACH row in the table:
   - Read field_name from the test name column
   - Read field_value from the result column in THE SAME ROW
   - Read field_unit from the unit column in THE SAME ROW
   - Read normal_range from the range column in THE SAME ROW
   - Do NOT take field_value from a different row even if current row is empty

2. EMPTY VALUE DETECTION:
   If field_value cell contains ANY of these, treat as EMPTY and return "":
   - Empty cell / blank
   - Only dashes: "-", "--", "—"
   - Only asterisks: "*", "**", "***"
   - Placeholders: "N/A", "n/a", "NA", "N.A", "nil", "none", "unknown"
   - Do NOT fill empty values with values from other rows or cells

3. is_normal calculation:
   - ONLY set is_normal if normal_range contains numeric range (e.g., "(12-16)", "0-200")
   - If normal_range is empty, missing, or non-numeric (e.g., "-", "*", empty string), set is_normal to null
   - If field_value is empty or non-numeric, set is_normal to null
   - Compare numeric field_value against numeric normal_range:
     * If value is within range: is_normal = true
     * If value is outside range: is_normal = false
   - If normal_range exists but you cannot parse it or compare, set is_normal to null

4. COMPLEX TABLES:
   - Handle tables with multiple sections (e.g., "HEMATOLOGY", "CLINICAL CHEMISTRY")
   - Each section may have its own column structure
   - Read each section's headers carefully
   - Maintain row alignment - each field_value must come from the same row as its field_name

STEP 4: JSON OUTPUT FORMAT
Return exactly one JSON object, no markdown, no explanations.

Use this schema:

{{
  "patient_name": "string (full name only, no labels or prefixes)",
  "patient_age": "string (age in years as number only, e.g. \"50\" or \"\" if unknown)",
  "patient_dob": "string (date YYYY-MM-DD or \"\" if unknown)",
  "patient_gender": "string (\"Male\" or \"Female\" or \"\")",
  "report_date": "string (YYYY-MM-DD or \"\")",
  "report_type": "{', '.join(REPORT_TYPES)} or free text",
  "doctor_names": "string (doctor names comma-separated, or \"\")",
  "medical_data": [
    {{
      "field_name": "string (test name, prefer English if available)",
      "field_value": "string (numeric value as text, or \"\" if empty/missing)",
      "field_unit": "string (unit like mg/dl, g/dL, etc., or \"\")",
      "normal_range": "string (reference range like \"(12-16)\", or \"\" if missing)",
      "is_normal": true or false or null (null if no normal_range or empty value),
      "category": "string (section name like \"HEMATOLOGY\" or \"\")",
      "notes": "string (any notes or \"\")"
    }}
  ]
}}
"""
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
                    response_format={"type": "json_object"},
                    max_tokens=2500,
                    timeout=120.0
                )
                response_text = completion.choices[0].message.content.strip()
                print(f"🔍 RAW RESPONSE for Image {idx}:\n{'-'*40}\n{response_text[:300]}...\n{'-'*40}")
                
                extracted_data = {}
                for attempt in range(2):
                    try:
                        import re
                        start_idx = response_text.find('{')
                        end_idx = response_text.rfind('}')
                        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                            json_str = response_text[start_idx:end_idx+1]
                            extracted_data = json.loads(json_str)
                            print(f"✅ JSON extracted for Image {idx} (attempt {attempt+1})")
                        else:
                            print(f"⚠️ No JSON brackets found in response for Image {idx} (attempt {attempt+1})")
                            print(f"RAW: {response_text[:200]}...")
                    except Exception as json_err:
                        print(f"⚠️ JSON Parsing Failed for Image {idx} (attempt {attempt+1}): {json_err}")
                        print(f"RAW RESPONSE: {response_text}")
                    
                    if extracted_data.get('medical_data') or attempt == 1:
                        break
                    
                    print(f"🔁 Retrying extraction for Image {idx} with table-focused prompt...")
                    table_only_prompt = f"""You are reading a medical LAB REPORT image (page {idx}/{total_pages}). 
The report may be in ENGLISH or ARABIC or BOTH.

CRITICAL RULES:
- Read each table row INDEPENDENTLY - each row is one test
- NEVER mix values from different rows or columns
- If a cell is empty (dash, asterisk, blank), return "" for that field_value
- Only set is_normal if normal_range contains numeric range, otherwise set null

Extract table data by mapping column headers:

Arabic headers:
- "الفحص" / "الاختبار" -> field_name
- "النتيجة" / "القيمة" -> field_value  
- "الوحدة" -> field_unit
- "المعدل الطبيعي" / "النتيجة الطبيعية" -> normal_range

English headers:
- "Test" / "Examination" -> field_name
- "Result" / "Value" -> field_value
- "Unit" -> field_unit
- "Normal Range" / "Reference Range" -> normal_range

For EACH row:
1. Read field_name from test name column
2. Read field_value from result column IN THE SAME ROW (not from other rows!)
3. Read field_unit from unit column IN THE SAME ROW
4. Read normal_range from range column IN THE SAME ROW
5. If field_value is empty/dash/asterisk, set it to ""
6. Set is_normal: null if no normal_range or empty value, otherwise true/false based on comparison

Return JSON with this structure only:
{{
  "medical_data": [
    {{
      "field_name": "Test name (prefer English if available)",
      "field_value": "numeric value as string, or \"\" if empty",
      "field_unit": "unit string, or \"\"",
      "normal_range": "range like \"(12-16)\", or \"\" if missing",
      "is_normal": true or false or null,
      "category": "section name like \"HEMATOLOGY\" or \"\"",
      "notes": "any notes or \"\""
    }}
  ]
}}
Return ONLY this JSON object, no markdown."""
                    content = [
                        {'type': 'text', 'text': table_only_prompt},
                        {
                            'type': 'image_url',
                            'image_url': {'url': f'data:image/{image_format};base64,{image_base64}'}
                        }
                    ]
                    completion = ollama_client.chat.completions.create(
                        model=Config.OLLAMA_MODEL,
                        messages=[{'role': 'user', 'content': content}],
                        temperature=0.1,
                        response_format={"type": "json_object"},
                        max_tokens=2500,
                        timeout=90.0
                    )
                    response_text = completion.choices[0].message.content.strip()
                    print(f"🔍 RAW RESPONSE (retry) for Image {idx}:\n{'-'*40}\n{response_text[:300]}...\n{'-'*40}")
                



                if extracted_data.get('is_medical_report') is False:
                     error_msg = extracted_data.get('reason', 'The uploaded file does not appear to be a valid medical report.')
                     print(f"⛔ Rejected as non-medical: {error_msg}")
                     continue
                
                if extracted_data.get('medical_data'):
                    new_items = extracted_data['medical_data']
                    
                    unique_new_items = []
                    existing_test_names = {str(item.get('field_name', '')).lower() for item in all_extracted_data}
                    
                    for item in new_items:
                        raw_test_name = item.get('field_name', '')
                        raw_test_val = item.get('field_value', '')
                        
                        test_name = str(raw_test_name).strip() if raw_test_name is not None else ''
                        test_val = str(raw_test_val).strip() if raw_test_val is not None else ''
                        
                        if not test_name or test_name.lower() in ['test name', 'test', 'الفحص', 'الاختبار']:
                            continue
                            
                        if test_name.lower() in existing_test_names:
                            print(f"⚠️ Duplicate test skipped: {test_name}")
                            continue
                        
                        # Enhanced empty value detection - recognize all empty indicators
                        empty_indicators = {'', ' ', '-', '--', '—', '*', '**', '***', 'n/a', 'na', 'n.a', 
                                          'nil', 'none', 'unknown', 'null', 'nul', 'not available', 
                                          'غير متوفر', 'غير موجود'}
                        test_val_cleaned = test_val.strip() if test_val else ''
                        test_val_lower = test_val_cleaned.lower()
                        
                        # If value is an empty indicator, set it to empty string but still process the field
                        if test_val_lower in empty_indicators or not test_val_cleaned:
                            # Set field_value to empty string - don't skip the field entirely
                            item['field_value'] = ''
                            # Still add the field but mark it as having no value
                            unique_new_items.append(item)
                            existing_test_names.add(test_name.lower())
                            continue
                        
                        # Check for qualitative results (normal/abnormal text)
                        qualitative_tokens = MedicalValidator.NORMAL_QUALITATIVE.union(MedicalValidator.ABNORMAL_QUALITATIVE)
                        is_qualitative = any(token in test_val_lower for token in qualitative_tokens)
                        
                        # Check if value contains numbers
                        has_digit = any(ch.isdigit() for ch in test_val_cleaned)
                        
                        # Accept if it has digits OR is a qualitative result
                        if has_digit or is_qualitative:
                            unique_new_items.append(item)
                            existing_test_names.add(test_name.lower())
                        else:
                            # Value doesn't look like a valid medical result - skip
                            print(f"⚠️ Skipping invalid test value: {test_name} = '{test_val_cleaned}'")
                    
                    all_extracted_data.extend(unique_new_items)
                    print(f"✅ Extracted {len(unique_new_items)} UNIQUE field(s) from page {idx}")
                
                # Capture patient info - merge intelligently, prefer most complete data
                new_name = str(extracted_data.get('patient_name', '') or '').strip()
                new_gender = str(extracted_data.get('patient_gender', '') or '').strip()
                new_age = str(extracted_data.get('patient_age', '') or '').strip()
                new_dob = str(extracted_data.get('patient_dob', '') or '').strip()
                new_doctor = str(extracted_data.get('doctor_names', '') or '').strip()
                new_report_date = str(extracted_data.get('report_date', '') or '').strip()
                
                current_name = str(patient_info.get('patient_name', '') or '').strip()
                current_gender = str(patient_info.get('patient_gender', '') or '').strip()
                current_age = str(patient_info.get('patient_age', '') or '').strip()
                current_dob = str(patient_info.get('patient_dob', '') or '').strip()
                
                # Merge patient info: use new data if current is empty, or if new is longer/more complete
                if not current_name and new_name:
                    patient_info['patient_name'] = new_name
                elif new_name and len(new_name) > len(current_name):
                    patient_info['patient_name'] = new_name
                    
                if not current_gender and new_gender:
                    patient_info['patient_gender'] = new_gender
                elif new_gender and not current_gender:
                    patient_info['patient_gender'] = new_gender
                    
                if not current_age and new_age:
                    patient_info['patient_age'] = new_age
                elif new_age and not current_age:
                    patient_info['patient_age'] = new_age
                    
                if not current_dob and new_dob:
                    patient_info['patient_dob'] = new_dob
                elif new_dob and not current_dob:
                    patient_info['patient_dob'] = new_dob
                    
                if new_doctor and not patient_info.get('doctor_names'):
                    patient_info['doctor_names'] = new_doctor
                elif new_doctor and new_doctor != patient_info.get('doctor_names'):
                    # Append if different
                    existing = patient_info.get('doctor_names', '')
                    if existing:
                        patient_info['doctor_names'] = f"{existing}, {new_doctor}"
                    else:
                        patient_info['doctor_names'] = new_doctor
                        
                if new_report_date and not patient_info.get('report_date'):
                    patient_info['report_date'] = new_report_date
                    
                # Keep report_type if not set
                if not patient_info.get('report_type') and extracted_data.get('report_type'):
                    patient_info['report_type'] = extracted_data.get('report_type')

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
        
        # Clean and extract patient name
        raw_name = patient_info.get('patient_name', '')
        cleaned_name = str(raw_name) if raw_name is not None else ''
        if cleaned_name:
            # Remove common prefixes and labels (both English and Arabic)
            cleaned_name = re.sub(r'^(Name|Patient Name|Patient|Mr\.?|Mrs\.?|Ms\.?|Dr\.?|اسم المريض|المريض|الاسم)\s*[:\-\.]?\s*', '', cleaned_name, flags=re.IGNORECASE)
            # Remove suffixes that might contain extra info
            cleaned_name = re.sub(r'\s+(Age|Sex|Gender|ID|Date|Ref|Dr|عمر|الجنس|رقم|تاريخ)\s*[:\-\.].*$', '', cleaned_name, flags=re.IGNORECASE)
            cleaned_name = cleaned_name.strip()
            name_lower = cleaned_name.replace(':', '').replace('-', '').strip().lower()
            # Reject if name is actually a label
            if name_lower in ['اسم المريض', 'patient name', 'name', 'المريض', 'الاسم', '']:
                cleaned_name = ''
            # Remove any remaining label-like prefixes
            if cleaned_name:
                cleaned_name = re.sub(r'^[:\-\.\s]+', '', cleaned_name)
                cleaned_name = re.sub(r'[:\-\.\s]+$', '', cleaned_name)

        # Extract and process date of birth and age
        raw_age = str(patient_info.get('patient_age', '') or '').strip()
        raw_dob = str(patient_info.get('patient_dob', '') or '').strip()
        cleaned_age = ''
        cleaned_dob = ''
        
        # Try to parse date of birth first (more reliable)
        dob_candidates = [raw_dob, raw_age]
        for text in dob_candidates:
            if not text:
                continue
            # Try various date formats
            # Format 1: YYYY-MM-DD
            try:
                dob_date = datetime.strptime(text[:10], '%Y-%m-%d').date()
                today = datetime.now(timezone.utc).date()
                age_years = today.year - dob_date.year - (
                    (today.month, today.day) < (dob_date.month, dob_date.day)
                )
                if 1 <= age_years <= 120:
                    cleaned_age = str(age_years)
                    cleaned_dob = dob_date.isoformat()
                    break
            except (ValueError, IndexError):
                pass
            
            # Format 2: DD/MM/YYYY or MM/DD/YYYY
            date_patterns = [
                (r'(\d{1,2})/(\d{1,2})/(\d{4})', lambda m: (int(m.group(3)), int(m.group(2)), int(m.group(1)))),  # DD/MM/YYYY
                (r'(\d{4})-(\d{1,2})-(\d{1,2})', lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),  # YYYY-MM-DD
            ]
            
            for pattern, parser in date_patterns:
                match = re.search(pattern, text)
                if match:
                    try:
                        year, month, day = parser(match)
                        dob_date = datetime(year, month, day).date()
                        today = datetime.now(timezone.utc).date()
                        age_years = today.year - dob_date.year - (
                            (today.month, today.day) < (dob_date.month, dob_date.day)
                        )
                        if 1 <= age_years <= 120:
                            cleaned_age = str(age_years)
                            cleaned_dob = dob_date.isoformat()
                            break
                    except (ValueError, IndexError):
                        continue
                if cleaned_age:
                    break
            if cleaned_age:
                break
        
        # If we have DOB but no age calculated, calculate it now
        if cleaned_dob and not cleaned_age:
            try:
                dob_date = datetime.strptime(cleaned_dob[:10], '%Y-%m-%d').date()
                today = datetime.now(timezone.utc).date()
                age_years = today.year - dob_date.year - (
                    (today.month, today.day) < (dob_date.month, dob_date.day)
                )
                if 1 <= age_years <= 120:
                    cleaned_age = str(age_years)
            except (ValueError, IndexError):
                pass
        
        # If no DOB found, try to extract age directly
        if not cleaned_age and raw_age:
            # Extract numeric age (handle formats like "50 years", "50 Y", "50")
            age_match = re.search(r'\b(\d{1,3})\b', raw_age)
            if age_match:
                try:
                    age_val = int(age_match.group(1))
                    if 1 <= age_val <= 120:
                        cleaned_age = str(age_val)
                except ValueError:
                    pass

        # Clean and normalize gender
        raw_gender = str(patient_info.get('patient_gender', '') or '').strip()
        gender_lower = raw_gender.lower()
        cleaned_gender = ''
        # Arabic: ذكر = Male, أنثى/انثى = Female
        # English: Male/M = Male, Female/F = Female
        if any(token in gender_lower for token in ['ذكر', 'male', 'm']):
            cleaned_gender = 'ذكر'  # Store in Arabic as per original code
        elif any(token in gender_lower for token in ['أنثى', 'انثى', 'female', 'f']):
            cleaned_gender = 'أنثى'

        raw_report_type = str(patient_info.get('report_type', '') or '').strip()
        cleaned_report_type = 'General'
        if raw_report_type:
            t = raw_report_type.lower()
            if 'cbc' in t or 'hematology' in t or 'complete blood count' in t:
                cleaned_report_type = 'Complete Blood Count (CBC)'
            elif 'chemistry' in t or 'clinical chemistry' in t:
                cleaned_report_type = 'Clinical Chemistry'
            else:
                cleaned_report_type = raw_report_type

        # Combine data
        final_data = {
            'patient_name': cleaned_name,
            'patient_age': cleaned_age,
            'patient_dob': cleaned_dob,
            'patient_gender': cleaned_gender,
            'report_date': patient_info.get('report_date', ''),
            'report_name': patient_info.get('report_name', 'Medical Report'),
            'report_type': cleaned_report_type,
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
                raw_original_name = item.get('field_name', '')
                original_name = str(raw_original_name).strip() if raw_original_name is not None else ''
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
                    
                    response = ollama_client.chat.completions.create(
                        model=Config.OLLAMA_MODEL, 
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

        if not allow_duplicate:
            yield f"data: {json.dumps({'percent': 85, 'message': 'Checking for duplicates...'})}\n\n"
            
            try:
                medical_data_list = final_data.get('medical_data', [])
                if len(medical_data_list) > 0:
                    report_hash = hashlib.sha256(json.dumps(medical_data_list, sort_keys=True).encode()).hexdigest()
                    
                    existing_report = Report.query.filter_by(
                        user_id=report_owner_id,
                        profile_id=profile_id,
                        report_hash=report_hash
                    ).first()
                    
                    if not existing_report and date_is_valid:
                        query = Report.query.filter(
                            Report.user_id == report_owner_id,
                            Report.report_date == report_date_obj
                        )
                        if profile_id is None:
                            query = query.filter(Report.profile_id.is_(None))
                        else:
                            query = query.filter(Report.profile_id == profile_id)
                        candidates = query.all()
                        
                        if candidates:
                            print(f"🔍 Found {len(candidates)} reports on {report_date_obj.date()}. Checking content similarity...")
                            
                            current_set = set()
                            for item in medical_data_list:
                                n = item.get('field_name', '').strip().lower()
                                v = str(item.get('field_value', '')).strip().lower()
                                if n and v:
                                    current_set.add((n, v))
                            
                            if len(current_set) > 0:
                                for cand in candidates:
                                    cand_fields = ReportField.query.filter_by(report_id=cand.id).all()
                                    cand_set = set()
                                    for f in cand_fields:
                                        n = f.field_name.strip().lower()
                                        v = f.field_value.strip().lower()
                                        cand_set.add((n, v))
                                    
                                    intersection = current_set.intersection(cand_set)
                                    overlap_ratio = len(intersection) / len(current_set) if len(current_set) > 0 else 0
                                    
                                    print(f"   - Candidate #{cand.id}: {len(intersection)}/{len(current_set)} matches ({overlap_ratio:.2f})")
                                    
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
            report_hash = hashlib.sha256(json.dumps(final_data['medical_data'], sort_keys=True).encode()).hexdigest()

            from utils.medical_mappings import categorize_report_type
            report_category = categorize_report_type(final_data.get('report_type'))

            raw_report_type = final_data.get('report_type')
            safe_report_type = None
            if isinstance(raw_report_type, str):
                raw_report_type = raw_report_type.strip()
                if len(raw_report_type) > 100:
                    safe_report_type = raw_report_type[:97] + '...'
                else:
                    safe_report_type = raw_report_type

            new_report = Report(
                user_id=report_owner_id,
                profile_id=profile_id,
                report_date=report_date_obj,
                report_hash=report_hash,
                report_name=final_data.get('report_name'),
                report_type=safe_report_type,
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
                rf = ReportFile(report_id=new_report.id, user_id=report_owner_id, **{k:v for k,v in f.items() if k!='is_pdf'})
                if f['is_pdf']:
                     # Find associated pages for PDF
                     pdf_pages = [img for img in images_list if img['source_filename'] == f['original_filename']]
                     for p in pdf_pages:
                         rf_page = ReportFile(
                             report_id=new_report.id, user_id=report_owner_id, 
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
                        user_id=report_owner_id,
                        field_name=item.get('field_name', 'Unknown'),
                        field_value=str(item.get('field_value', '')),
                        field_unit=str(item.get('field_unit', '')),
                        normal_range=str(item.get('normal_range', '')),
                        is_normal=item.get('is_normal') if isinstance(item.get('is_normal'), bool) else None,
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
