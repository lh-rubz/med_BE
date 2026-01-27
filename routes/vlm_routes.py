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
import easyocr
from PIL import Image
import io
import re
import pytesseract

from models import db, User, Report, ReportField, ReportFile, MedicalSynonym
from config import ollama_client, Config
from utils.medical_validator import validate_medical_data, MedicalValidator
from utils.medical_mappings import add_new_alias
from utils.vlm_prompts import get_main_vlm_prompt, get_table_retry_prompt, get_personal_info_prompt
from utils.vlm_correction import analyze_extraction_issues, generate_corrective_prompt, generate_prompt_enhancement_request
from utils.vlm_self_prompt import get_report_analysis_prompt, get_custom_extraction_prompt
from ollama import Client
from utils.extract_personal_info import extract_personal_info, extract_medical_data

# Create namespace
vlm_ns = Namespace('vlm', description='VLM and Report operations')

# Helper function to normalize gender values
def normalize_gender(gender_value):
    """Convert any gender representation to English Male/Female."""
    if not gender_value:
        return ''
    gender_str = str(gender_value).strip()
    gender_lower = gender_str.lower()
    
    # Male variations
    if gender_lower in ['male', 'm', 'ذكر', 'ذكر ', ' ذكر']:
        return 'Male'
    # Female variations
    elif gender_lower in ['female', 'f', 'أنثى', 'انثى', 'أنثي', 'انثي']:
        return 'Female'
    # If it's already correct, return it
    elif gender_str in ['Male', 'Female']:
        return gender_str
    # Unknown format
    else:
        print(f"⚠️ Unknown gender format: '{gender_str}' - clearing")
        return ''

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
            
            # Step 1: Extract Personal Information (Name, Gender, Age, etc.)
            print(f"🤖 Step 1: Extracting patient personal information...")
            yield f"data: {json.dumps({'percent': current_progress + 5, 'message': f'Extracting patient info from page {idx}...'})}\n\n"
            
            personal_info_prompt = get_personal_info_prompt(idx, total_pages)
            personal_data = {}
            correction_pass = 0
            max_correction_passes = 5
            
            try:
                image_base64 = base64.b64encode(image_info['data']).decode('utf-8')
                image_format = image_info['format']
                
                # Variables for enhanced prompt
                enhanced_prompt = None
                key_observations = []
                
                # ITERATIVE CORRECTION LOOP: Keep fixing until no errors
                while correction_pass < max_correction_passes:
                    correction_pass += 1
                    print(f"\n🔄 Personal Info Extraction Pass {correction_pass}/{max_correction_passes}")
                    
                    if correction_pass == 1:
                        # First pass: Use main prompt
                        prompt_to_use = personal_info_prompt
                    else:
                        # Subsequent passes: Analyze and enhance
                        analysis = analyze_extraction_issues(personal_data)
                        if not analysis['has_issues']:
                            print(f"✅ No issues found in personal info - extraction complete!")
                            break
                        
                        print(f"⚠️ Found {analysis['issue_count']} issue(s), generating enhanced prompt...")
                        for issue in analysis['issues'][:5]:
                            print(f"   - {issue['type']}: {issue['reason']}")
                        
                        # On second pass, ask model to enhance the prompt for this specific report
                        if correction_pass == 2 and not enhanced_prompt:
                            print(f"🧠 Generating report-specific enhanced prompt...")
                            enhancement_request = generate_prompt_enhancement_request(
                                personal_info_prompt, personal_data, analysis
                            )
                            
                            enhancement_content = [
                                {'type': 'text', 'text': enhancement_request},
                                {
                                    'type': 'image_url',
                                    'image_url': {'url': f'data:image/{image_format};base64,{image_base64}'}
                                }
                            ]
                            
                            try:
                                enhancement_completion = ollama_client.chat.completions.create(
                                    model=Config.OLLAMA_MODEL,
                                    messages=[{'role': 'user', 'content': enhancement_content}],
                                    temperature=0.2,
                                    response_format={"type": "json_object"},
                                    max_tokens=1500,
                                    timeout=60.0
                                )
                                enhancement_response = enhancement_completion.choices[0].message.content.strip()
                                
                                # Parse enhancement response
                                start_idx = enhancement_response.find('{')
                                end_idx = enhancement_response.rfind('}')
                                if start_idx != -1 and end_idx != -1:
                                    enhancement_data = json.loads(enhancement_response[start_idx:end_idx+1])
                                    enhanced_prompt = enhancement_data.get('enhanced_prompt', '')
                                    key_observations = enhancement_data.get('key_observations', [])
                                    
                                    print(f"✅ Enhanced prompt generated!")
                                    print(f"📝 Key observations:")
                                    for obs in key_observations[:3]:
                                        print(f"   - {obs}")
                            except Exception as enh_err:
                                print(f"⚠️ Prompt enhancement failed: {enh_err}, using standard correction")
                        
                        # Generate corrective prompt (uses enhanced prompt if available)
                        prompt_to_use = generate_corrective_prompt(
                            personal_data, analysis, idx, total_pages, 
                            enhanced_prompt=enhanced_prompt,
                            original_prompt=personal_info_prompt
                        )
                    
                    content = [
                        {'type': 'text', 'text': prompt_to_use},
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
                        max_tokens=800,
                        timeout=60.0
                    )
                    response_text = completion.choices[0].message.content.strip()
                    print(f"✅ Response (Pass {correction_pass}):\n{'-'*40}\n{response_text[:200]}...\n{'-'*40}")
                    
                    try:
                        start_idx = response_text.find('{')
                        end_idx = response_text.rfind('}')
                        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                            json_str = response_text[start_idx:end_idx+1]
                            personal_data = json.loads(json_str)
                            
                            # POST-PROCESSING: Normalize gender
                            original_gender = personal_data.get('patient_gender', '')
                            if original_gender:
                                normalized_gender = normalize_gender(original_gender)
                                if normalized_gender != original_gender:
                                    print(f"🔧 Normalized gender: '{original_gender}' -> '{normalized_gender}'")
                                personal_data['patient_gender'] = normalized_gender
                            
                            print(f"✅ Personal info extracted for Page {idx} (Pass {correction_pass})")
                    except Exception as json_err:
                        print(f"⚠️ JSON Parsing Failed (Pass {correction_pass}): {json_err}")
                        personal_data = {}
                        break
                
                # Final check
                if correction_pass >= max_correction_passes:
                    final_analysis = analyze_extraction_issues(personal_data)
                    if final_analysis['has_issues']:
                        print(f"⚠️ Max correction passes reached with {final_analysis['issue_count']} remaining issue(s)")
                        
            except Exception as e:
                print(f"⚠️ Personal info extraction error (Page {idx}): {str(e)}")
                personal_data = {}
            
            print(f"📋 Final Personal Info: Name='{personal_data.get('patient_name')}', Gender='{personal_data.get('patient_gender')}', Doctor='{personal_data.get('doctor_names')}'")
            
            # Step 2: SELF-PROMPTING APPROACH - Let model analyze and create its own prompt
            print(f"🤖 Step 2: Analyzing report structure and creating custom extraction prompt...")
            yield f"data: {json.dumps({'percent': current_progress + 10, 'message': f'Analyzing report structure on page {idx}...'})}\n\n"
            
            medical_extracted = {}
            report_analysis = {}
            
            try:
                image_base64 = base64.b64encode(image_info['data']).decode('utf-8')
                image_format = image_info['format']
                
                # STEP 1: Ask model to analyze the report and create custom extraction instructions
                print(f"🧠 STEP 1: Asking model to analyze report structure...")
                analysis_prompt = get_report_analysis_prompt(idx, total_pages)
                
                analysis_content = [
                    {'type': 'text', 'text': analysis_prompt},
                    {
                        'type': 'image_url',
                        'image_url': {'url': f'data:image/{image_format};base64,{image_base64}'}
                    }
                ]
                
                analysis_completion = ollama_client.chat.completions.create(
                    model=Config.OLLAMA_MODEL,
                    messages=[{'role': 'user', 'content': analysis_content}],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    max_tokens=2500,
                    timeout=90.0
                )
                
                analysis_response = analysis_completion.choices[0].message.content.strip()
                print(f"📊 Analysis response received:\n{'-'*60}\n{analysis_response}\n{'-'*60}")
                
                # Parse analysis
                try:
                    start_idx = analysis_response.find('{')
                    end_idx = analysis_response.rfind('}')
                    if start_idx != -1 and end_idx != -1:
                        report_analysis = json.loads(analysis_response[start_idx:end_idx+1])
                        total_rows = report_analysis.get('total_test_rows', 20)
                        print(f"✅ Report analyzed:")
                        print(f"   - Language: {report_analysis.get('report_language')}")
                        print(f"   - Total test rows: {total_rows}")
                        print(f"   - First 5 tests: {report_analysis.get('first_5_test_names', [])}")
                        print(f"   - Last 5 tests: {report_analysis.get('last_5_test_names', [])}")
                        print(f"   - Column map: {report_analysis.get('column_map', {})}")
                except Exception as parse_err:
                    print(f"⚠️ Failed to parse analysis: {parse_err}")
                
                # STEP 2: Use the custom instructions to extract data
                print(f"\n🔍 STEP 2: Extracting data using custom instructions...")
                total_rows_text = report_analysis.get("total_test_rows", "all")
                yield f"data: {json.dumps({'percent': current_progress + 15, 'message': f'Extracting {total_rows_text} medical tests from page {idx}...'})}\n\n"
                
                custom_prompt = get_custom_extraction_prompt(report_analysis, idx, total_pages)
                
                extraction_content = [
                    {'type': 'text', 'text': custom_prompt},
                    {
                        'type': 'image_url',
                        'image_url': {'url': f'data:image/{image_format};base64,{image_base64}'}
                    }
                ]
                
                extraction_completion = ollama_client.chat.completions.create(
                    model=Config.OLLAMA_MODEL,
                    messages=[{'role': 'user', 'content': extraction_content}],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    max_tokens=5000,
                    timeout=180.0
                )
                
                extraction_response = extraction_completion.choices[0].message.content.strip()
                print(f"📦 Extraction response received:\n{'-'*60}\n{extraction_response[:500]}...\n{'-'*60}")
                
                # Parse extraction
                try:
                    start_idx = extraction_response.find('{')
                    end_idx = extraction_response.rfind('}')
                    if start_idx != -1 and end_idx != -1:
                        json_str = extraction_response[start_idx:end_idx+1]
                        medical_extracted = json.loads(json_str)
                        
                        item_count = len(medical_extracted.get('medical_data', []))
                        expected_count = report_analysis.get('total_test_rows', 0)
                        print(f"✅ Extracted {item_count} medical items (expected: {expected_count})")
                        
                        if item_count < expected_count:
                            print(f"⚠️⚠️⚠️ CRITICAL: Only extracted {item_count}/{expected_count} items!")
                            print(f"   ANALYSIS FOUND {expected_count} ROWS BUT EXTRACTION ONLY GOT {item_count}!")
                            print(f"   First 3 items: {[item.get('field_name', 'N/A') for item in medical_extracted.get('medical_data', [])[:3]]}")
                            print(f"   Last 3 items: {[item.get('field_name', 'N/A') for item in medical_extracted.get('medical_data', [])[-3:]]}")
                        elif item_count == 9 and expected_count > 15:
                            print(f"🚨🚨🚨 SEVERE UNDER-EXTRACTION: Analysis found {expected_count} rows but got only 9!")
                            print(f"   This is likely the model stopping early!")
                        
                        # Check for name confusion
                        extracted_patient = str(medical_extracted.get('patient_name', '')).strip()
                        extracted_doctor = str(medical_extracted.get('doctor_names', '')).strip()
                        if extracted_patient and extracted_doctor:
                            # Check if they're too similar (might be mixed up)
                            if extracted_patient.lower() in extracted_doctor.lower() or extracted_doctor.lower() in extracted_patient.lower():
                                print(f"⚠️ WARNING: Patient and Doctor names might be mixed up!")
                                print(f"   Patient: '{extracted_patient}'")
                                print(f"   Doctor: '{extracted_doctor}'")
                except Exception as json_err:
                    print(f"⚠️ JSON parsing failed: {json_err}")
                    medical_extracted = {}
                
                # Use the extracted medical data
                extracted_data = medical_extracted
                
            except Exception as e:
                print(f"⚠️ Medical data extraction error (Page {idx}): {str(e)}")
                extracted_data = {}
            
            # Debug: Print what we got
            print(f"📊 Extracted data keys: {list(extracted_data.keys()) if extracted_data else 'EMPTY'}")
            print(f"📊 Has medical_data key: {extracted_data.get('medical_data') is not None}")
            if extracted_data.get('medical_data'):
                print(f"📊 Medical data count: {len(extracted_data['medical_data'])} items")
            
            # Continue processing the extracted data
            if extracted_data.get('is_medical_report') is False:
                error_msg = extracted_data.get('reason', 'The uploaded file does not appear to be a valid medical report.')
                print(f"⛔ Rejected as non-medical: {error_msg}")
                continue
            
            unique_new_items = []  # Initialize outside to avoid scope error
            
            if extracted_data.get('medical_data'):
                new_items = extracted_data['medical_data']
                
                existing_test_names = {str(item.get('field_name', '')).lower() for item in all_extracted_data}
                
                for item in new_items:
                    raw_test_name = item.get('field_name', '')
                    raw_test_val = item.get('field_value', '')
                    raw_test_unit = item.get('field_unit', '')
                    raw_test_range = item.get('normal_range', '')
                    
                    test_name = str(raw_test_name).strip() if raw_test_name is not None else ''
                    test_val = str(raw_test_val).strip() if raw_test_val is not None else ''
                    test_unit = str(raw_test_unit).strip() if raw_test_unit is not None else ''
                    test_range = str(raw_test_range).strip() if raw_test_range is not None else ''
                    
                    # SKIP IF: field_name is empty or is a header label
                    if not test_name or test_name.lower() in ['test name', 'test', 'الفحص', 'الاختبار']:
                        print(f"⚠️ Skipping row with empty/label field_name: '{test_name}'")
                        continue
                    
                    # SKIP IF: duplicate test name already processed
                    if test_name.lower() in existing_test_names:
                        print(f"⚠️ Duplicate test skipped: {test_name}")
                        continue
                    
                    # CRITICAL: Detect misalignment - value looks like a unit or range
                    # Be STRICT about catching corruption but don't be overly paranoid
                    unit_symbols = {'%', 'mg/dl', 'mg/dL', 'U/L', 'K/uL', 'M/uL', 'g/dL', 'fL', 'pg', 'cells/L', 'cells/uL', 'mmol/L'}
                    
                    # Check 1: Is value a unit symbol (OBVIOUS corruption)
                    is_value_a_unit = test_val in unit_symbols
                    
                    # Check 2: Is value a range like "(4-11)" (OBVIOUS corruption)
                    is_value_a_range = test_val.startswith('(') and test_val.endswith(')') and '-' in test_val
                    
                    # Check 3: Is unit all digits (OBVIOUS corruption - value leak into unit column)
                    is_unit_a_value = test_unit and test_unit.replace('.', '').isdigit()
                    
                    # Check 4: Is unit a parenthesized range (OBVIOUS corruption)
                    is_unit_a_range = test_unit.startswith('(') and test_unit.endswith(')') and '-' in test_unit
                    
                    # Check 5: Is range a single number without dashes (OBVIOUS corruption - value leaked)
                    is_range_a_value = test_range and not test_range.startswith('(') and not '-' in test_range and test_range.replace('.', '').isdigit()
                    
                    # Check 6: Is range just a unit symbol (OBVIOUS corruption)
                    is_range_a_unit = test_range in unit_symbols
                    
                    if is_value_a_unit or is_value_a_range or is_unit_a_value or is_unit_a_range or is_range_a_value or is_range_a_unit:
                        print(f"🚨 MISALIGNMENT DETECTED in row '{test_name}':")
                        if is_value_a_unit:
                            print(f"   Value is unit symbol: '{test_val}'")
                        if is_value_a_range:
                            print(f"   Value is range format: '{test_val}'")
                        if is_unit_a_value:
                            print(f"   Unit is numeric: '{test_unit}'")
                        if is_unit_a_range:
                            print(f"   Unit is range format: '{test_unit}'")
                        if is_range_a_value:
                            print(f"   Range is single number: '{test_range}'")
                        if is_range_a_unit:
                            print(f"   Range is unit symbol: '{test_range}'")
                        print(f"   SKIPPING to avoid data corruption")
                        continue

                    
                    # Enhanced empty value detection - recognize all empty indicators
                    empty_indicators = {'', ' ', '-', '--', '—', '*', '**', '***', 'n/a', 'na', 'n.a', 
                                      'nil', 'none', 'unknown', 'null', 'nul', 'not available', '.', '..',
                                      'غير متوفر', 'غير موجود'}
                    test_val_cleaned = test_val.strip() if test_val else ''
                    test_val_lower = test_val_cleaned.lower()
                    
                    # SKIP rows with EMPTY field_value (as per original logic)
                    if test_val_lower in empty_indicators or not test_val_cleaned:
                        print(f"⚠️ Skipping row with empty field_value: {test_name}")
                        continue
                    
                    # Also check normal_range for empty indicators (but don't skip - allow missing ranges)
                    normal_range_raw = str(item.get('normal_range', '') or '').strip()
                    normal_range_lower = normal_range_raw.lower()
                    
                    # Clean normal_range if it's an empty indicator - convert to empty string
                    if normal_range_raw in ['-', '--', '—', '*', '(-)', '.'] or normal_range_lower in empty_indicators:
                        # Check if it actually contains numbers - if not, it's empty
                        if not any(ch.isdigit() for ch in normal_range_raw):
                            item['normal_range'] = ''
                            print(f"⚠️ Cleaned empty normal_range for {test_name}: '{normal_range_raw}' -> ''")

                    
                    # Check for qualitative results (normal/abnormal text)
                    qualitative_tokens = MedicalValidator.NORMAL_QUALITATIVE.union(MedicalValidator.ABNORMAL_QUALITATIVE)
                    is_qualitative = any(token in test_val_lower for token in qualitative_tokens)
                    
                    # Check if value contains numbers
                    has_digit = any(ch.isdigit() for ch in test_val_cleaned)
                    
                    # Accept if it has digits OR is a qualitative result
                    if has_digit or is_qualitative:
                        unique_new_items.append(item)
                        existing_test_names.add(test_name.lower())
                        print(f"✅ Added field: {test_name} = '{test_val_cleaned}' {test_unit}")
                    else:
                        # Value doesn't look like a valid medical result - skip
                        print(f"⚠️ Skipping invalid test value: {test_name} = '{test_val_cleaned}'")
            
            all_extracted_data.extend(unique_new_items)
            print(f"✅ Extracted {len(unique_new_items)} field(s) from page {idx}")
            
            # Merge personal info: Use the dedicated personal_info extraction (Step 1)
            # This is more accurate than trying to extract it with medical data
            personal_name = str(personal_data.get('patient_name', '') or '').strip()
            personal_gender = normalize_gender(personal_data.get('patient_gender', ''))
            personal_age = str(personal_data.get('patient_age', '') or '').strip()
            personal_dob = str(personal_data.get('patient_dob', '') or '').strip()
            personal_doctor = str(personal_data.get('doctor_names', '') or '').strip()
            personal_report_date = str(personal_data.get('report_date', '') or '').strip()
            
            # Also extract from medical_data prompt as fallback
            fallback_name = str(extracted_data.get('patient_name', '') or '').strip()
            fallback_gender = normalize_gender(extracted_data.get('patient_gender', ''))
            fallback_age = str(extracted_data.get('patient_age', '') or '').strip()
            fallback_dob = str(extracted_data.get('patient_dob', '') or '').strip()
            fallback_doctor = str(extracted_data.get('doctor_names', '') or '').strip()
            fallback_report_date = str(extracted_data.get('report_date', '') or '').strip()
            
            # PRIORITY: Use personal_data (from dedicated personal info prompt) first,
            # fallback to medical_data extraction if personal_data is empty
            new_name = personal_name or fallback_name
            new_gender = personal_gender or fallback_gender
            new_age = personal_age or fallback_age
            new_dob = personal_dob or fallback_dob
            new_doctor = personal_doctor or fallback_doctor
            new_report_date = personal_report_date or fallback_report_date
            
            # Smart detection: If new_name starts with "Dr", "Doctor", "دكتور", etc, it might be doctor name
            doctor_prefixes = ['dr', 'doctor', 'dr.', 'دكتور', 'طبيب', 'د.']
            name_lower = new_name.lower() if new_name else ''
            if any(name_lower.startswith(prefix) for prefix in doctor_prefixes):
                # This is likely a doctor name, extract actual name and use as doctor
                cleaned_doctor_name = re.sub(r'^(dr\.?|doctor|دكتور|طبيب|د\.)\s*', '', new_name, flags=re.IGNORECASE).strip()
                print(f"⚠️ Detected doctor name in patient field: '{new_name}' -> using as doctor")
                new_doctor = cleaned_doctor_name or new_doctor
                new_name = ''  # Clear this so we don't use doctor name as patient name
            
            # Debug: Print what we extracted from this page
            print(f"📋 Page {idx} - Extracted patient info:")
            print(f"   Name: '{new_name}' (from {'personal' if personal_name else 'fallback'})")
            print(f"   Gender: '{new_gender}' (from {'personal' if personal_gender else 'fallback'})")
            print(f"   Age: '{new_age}', DOB: '{new_dob}'")
            print(f"   Doctor: '{new_doctor}' (from {'personal' if personal_doctor else 'fallback'})")
            print(f"   Report Date: '{new_report_date}'")
            
            current_name = str(patient_info.get('patient_name', '') or '').strip()
            current_gender = str(patient_info.get('patient_gender', '') or '').strip()
            current_age = str(patient_info.get('patient_age', '') or '').strip()
            current_dob = str(patient_info.get('patient_dob', '') or '').strip()
            current_doctor = str(patient_info.get('doctor_names', '') or '').strip()
            
            # Note: With dedicated personal info extraction, we should have cleaner data
            # The previous "SMART FIX" for swapping patient/doctor names should be less necessary
            
            # Merge patient info: use new data if current is empty, or if new is longer/more complete
            # Since personal_data comes from dedicated prompt, it should be cleaner than fallback data
            if new_name and len(new_name) > 2:  # At least 3 characters
                if not current_name or (len(new_name) > len(current_name) and len(new_name) > 3):
                    patient_info['patient_name'] = new_name
            
            # Merge doctor names: Combine if we have both
            if new_doctor and len(new_doctor) > 2:
                if not current_doctor:
                    patient_info['doctor_names'] = new_doctor
                    print(f"✅ Set doctor name: '{new_doctor}'")
                elif new_doctor != current_doctor and len(new_doctor) > 2:
                    # Combine doctor names if different (might be from different pages)
                    patient_info['doctor_names'] = f"{current_doctor} / {new_doctor}"
                    print(f"✅ Updated doctor name: '{patient_info['doctor_names']}'")
            else:
                if new_doctor:
                    print(f"⚠️ Doctor name too short, skipping: '{new_doctor}'")
                    print(f"✅ Updated patient_name: {new_name}")
                
            # Gender: At this point new_gender should already be normalized to "Male" or "Female"
            if new_gender in ['Male', 'Female']:
                if not current_gender or current_gender != new_gender:
                    patient_info['patient_gender'] = new_gender
                    print(f"✅ Updated patient_gender: {new_gender}")
                
            # Age: validate it's a reasonable number
            if new_age:
                try:
                    age_num = int(new_age)
                    if 1 <= age_num <= 120:
                        if not current_age or current_age != new_age:
                            patient_info['patient_age'] = new_age
                            print(f"✅ Updated patient_age: {new_age}")
                except (ValueError, TypeError):
                    pass
                
            # Date of birth
            if new_dob and len(new_dob) >= 8:  # At least YYYY-MM-DD format
                if not current_dob:
                    patient_info['patient_dob'] = new_dob
                    print(f"✅ Updated patient_dob: {new_dob}")
                
            # Doctor names - separate field
            if new_doctor and len(new_doctor) > 2:
                if not patient_info.get('doctor_names'):
                    patient_info['doctor_names'] = new_doctor
                elif new_doctor != patient_info.get('doctor_names') and new_doctor.lower() not in patient_info.get('doctor_names', '').lower():
                    # Append if different
                    existing = patient_info.get('doctor_names', '')
                    if existing:
                        patient_info['doctor_names'] = f"{existing}, {new_doctor}"
                    else:
                        patient_info['doctor_names'] = new_doctor
                    
            if new_report_date and len(new_report_date) >= 8:
                # Extract only YYYY-MM-DD part if timestamp is present
                date_only = new_report_date[:10] if ' ' in new_report_date or 'T' in new_report_date else new_report_date
                if not patient_info.get('report_date'):
                    patient_info['report_date'] = date_only
                    print(f"✅ Updated report_date: {date_only}")
                
            # Keep report_type if not set
            if not patient_info.get('report_type') and extracted_data.get('report_type'):
                patient_info['report_type'] = extracted_data.get('report_type')

            print(f"✅ Page {idx} Analysis Complete. Found {len(extracted_data.get('medical_data', []))} data points.")

        # VALIDATION: Check if we massively under-extracted
        fields_found = len(all_extracted_data)
        print(f"\n{'='*80}")
        print(f"📊 EXTRACTION SUMMARY AFTER ALL PAGES:")
        print(f"   Total fields extracted: {fields_found}")
        if fields_found <= 10 and fields_found > 0:
            print(f"   ⚠️⚠️⚠️ WARNING: Only extracted {fields_found} fields")
            print(f"   This seems too low! Check if extraction is stopping early!")
        print(f"{'='*80}\n")

        # FINAL VALIDATION: Check if doctor name is mixed up with patient name
        final_patient = str(patient_info.get('patient_name', '')).strip()
        final_doctor = str(patient_info.get('doctor_names', '')).strip()
        
        if final_patient and final_doctor:
            # Check for contamination: doctor name contains patient name or vice versa
            patient_words = set(final_patient.lower().split())
            doctor_words = set(final_doctor.lower().split())
            overlap = patient_words.intersection(doctor_words)
            
            if len(overlap) > 0:
                print(f"⚠️ WARNING: Patient and Doctor names have overlap: {overlap}")
                print(f"   Patient: '{final_patient}'")
                print(f"   Doctor: '{final_doctor}'")
                
                # If they're suspiciously similar, clear doctor name
                if final_patient.lower().strip() == final_doctor.lower().strip():
                    print(f"🚨 CRITICAL: Patient and Doctor names are IDENTICAL - clearing doctor name!")
                    patient_info['doctor_names'] = ''
                    final_doctor = ''
        if not all_extracted_data:
             error_msg = 'No valid medical data found in any of the uploaded images.'
             yield f"data: {json.dumps({'error': error_msg, 'code': 'NO_DATA_FOUND'})}\n\n"
             return

        # Step 3: Validation
        yield f"data: {json.dumps({'percent': 75, 'message': 'Double-checking the results...'})}\n\n"
        print(f"🔍 Validating aggregated data ({len(all_extracted_data)} total items)...")
        
        # Debug: Print final patient info before cleaning
        print(f"\n{'='*80}")
        print(f"📊 FINAL PATIENT INFO BEFORE CLEANING:")
        print(f"   Name: '{patient_info.get('patient_name', '')}'")
        print(f"   Gender: '{patient_info.get('patient_gender', '')}'")
        print(f"   Age: '{patient_info.get('patient_age', '')}'")
        print(f"   DOB: '{patient_info.get('patient_dob', '')}'")
        print(f"{'='*80}\n")
        
        # Clean and extract patient name - STRICT REJECTION OF LABELS
        raw_name = patient_info.get('patient_name', '')
        cleaned_name = str(raw_name) if raw_name is not None else ''
        if cleaned_name:
            # First, reject common labels (Arabic and English) - exact match or starts with
            label_patterns = [
                'رقم المريض', 'اسم المريض', 'المريض', 'الاسم', 'رقم', 'اسم',
                'patient name', 'patient id', 'patient number', 'name', 'patient',
                'دكتور', 'طبيب', 'doctor', 'dr.'
            ]
            name_lower_orig = cleaned_name.lower().strip()
            for label in label_patterns:
                if name_lower_orig == label.lower() or name_lower_orig.startswith(label.lower() + ':'):
                    print(f"⚠️ Rejected name (matches label): '{cleaned_name}'")
                    cleaned_name = ''
                    break
            
            if cleaned_name:
                # Remove common prefixes and labels (both English and Arabic)
                cleaned_name = re.sub(r'^(Name|Patient Name|Patient|Mr\.?|Mrs\.?|Ms\.?|Dr\.?|اسم المريض|المريض|الاسم|رقم المريض)\s*[:\-\.]?\s*', '', cleaned_name, flags=re.IGNORECASE)
                # Remove suffixes that might contain extra info
                cleaned_name = re.sub(r'\s+(Age|Sex|Gender|ID|Date|Ref|Dr|عمر|الجنس|رقم|تاريخ)\s*[:\-\.].*$', '', cleaned_name, flags=re.IGNORECASE)
                cleaned_name = cleaned_name.strip()
                name_lower = cleaned_name.replace(':', '').replace('-', '').strip().lower()
                
                # Reject if name is actually a label or too short/numeric
                if name_lower in ['اسم المريض', 'patient name', 'name', 'المريض', 'المرضى', 'الاسم', 'رقم المريض', 'رقم', 'اسم', 'patient', 'patients', '']:
                    cleaned_name = ''
                elif len(cleaned_name) < 3 or cleaned_name.strip().isdigit():
                    cleaned_name = ''
                else:
                    # Remove any remaining label-like prefixes/suffixes
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

        # Clean and normalize gender - be very strict
        raw_gender = str(patient_info.get('patient_gender', '') or '').strip()
        gender_lower = raw_gender.lower().strip()
        cleaned_gender = ''
        
        # Very strict matching - only accept clear gender indicators
        # Convert to ENGLISH: Male/Female (not Arabic)
        male_indicators = ['ذكر', 'male', 'm']
        female_indicators = ['أنثى', 'انثى', 'انتى', 'أنتى', 'female', 'f']
        
        # Check for male (must match exactly or start with one of these)
        if any(gender_lower == ind.lower() for ind in male_indicators) or any(gender_lower.startswith(ind.lower()) for ind in male_indicators if len(ind) > 1):
            if not any(gender_lower.startswith(fem.lower()) for fem in female_indicators):
                cleaned_gender = 'Male'  # ENGLISH, not Arabic
                print(f"✅ Cleaned gender: {raw_gender} -> {cleaned_gender}")
        # Check for female
        elif any(gender_lower == ind.lower() for ind in female_indicators) or any(gender_lower.startswith(ind.lower()) for ind in female_indicators if len(ind) > 1):
            cleaned_gender = 'Female'  # ENGLISH, not Arabic
            print(f"✅ Cleaned gender: {raw_gender} -> {cleaned_gender}")
        elif raw_gender:
            # If we have a gender value but it doesn't match, log it for debugging
            print(f"⚠️ Unrecognized gender value: '{raw_gender}' (keeping empty)")

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
        
        # Debug: Print final cleaned patient data
        print(f"\n{'='*80}")
        print(f"✅ FINAL CLEANED PATIENT DATA:")
        print(f"   Name: '{cleaned_name}'")
        print(f"   Gender: '{cleaned_gender}'")
        print(f"   Age: '{cleaned_age}'")
        print(f"   DOB: '{cleaned_dob}'")
        print(f"   Doctor: '{patient_info.get('doctor_names', '')}'")
        print(f"   Total fields extracted: {len(all_extracted_data)}")
        print(f"{'='*80}\n")
        
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

@vlm_ns.route('/extract-personal-info')
class ExtractPersonalInfo(Resource):
    def post(self):
        """
        Extract personal information from a medical report.
        Expects a JSON payload with a 'report_text' field.
        """
        data = request.get_json()
        if not data or 'report_text' not in data:
            return {"error": "Missing 'report_text' in request body."}, 400

        report_text = data['report_text']
        extracted_info = extract_personal_info(report_text)

        return {"extracted_info": extracted_info}, 200

@vlm_ns.route('/extract-personal-info-file')
class ExtractPersonalInfoFile(Resource):
    def post(self):
        """
        Extract personal information from an uploaded medical report file (image or PDF).
        Accepts a file upload.
        """
        if 'file' not in request.files:
            return {"error": "No file uploaded."}, 400

        uploaded_file = request.files['file']
        if not uploaded_file:
            return {"error": "No file provided."}, 400

        try:
            # Determine file type and extract text
            if uploaded_file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                # Process image file
                image = Image.open(uploaded_file)
                extracted_text = pytesseract.image_to_string(image)
            elif uploaded_file.filename.lower().endswith('.pdf'):
                # Process PDF file
                pdf_document = fitz.open(stream=uploaded_file.read(), filetype="pdf")
                extracted_text = ""
                for page in pdf_document:
                    extracted_text += page.get_text()
            else:
                return {"error": "Unsupported file type. Please upload a PDF or image."}, 400

            # Extract personal information
            extracted_info = extract_personal_info(extracted_text)
            return {"extracted_info": extracted_info}, 200

        except Exception as e:
            return {"error": f"Failed to process file: {str(e)}"}, 500

@vlm_ns.route('/extract-medical-info-file')
class ExtractMedicalInfoFile(Resource):
    def post(self):
        """
        Extract personal and medical information from an uploaded medical report file (image or PDF).
        Accepts a file upload.
        """
        if 'file' not in request.files:
            return {"error": "No file uploaded."}, 400

        uploaded_file = request.files['file']
        if not uploaded_file:
            return {"error": "No file provided."}, 400

        try:
            extracted_text = ""
            if uploaded_file.filename.lower().endswith('.pdf'):
                # Process multi-page PDF files
                pdf_document = fitz.open(stream=uploaded_file.read(), filetype="pdf")
                for page in pdf_document:
                    extracted_text += page.get_text()
            elif uploaded_file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                # Process image files using easyocr
                reader = easyocr.Reader(['en'])
                result = reader.readtext(uploaded_file.read(), detail=0)
                extracted_text = "\n".join(result)
            else:
                return {"error": "Unsupported file type. Please upload a PDF or image."}, 400

            # Extract personal and medical information
            personal_info = extract_personal_info(extracted_text)
            medical_info = extract_medical_data(extracted_text)

            # Ensure fields are clean and consistent
            cleaned_medical_info = {
                field: details
                for field, details in medical_info.items()
                if details.get("value") or details.get("normal_range")
            }

            return {
                "personal_info": personal_info,
                "medical_info": cleaned_medical_info
            }, 200

        except Exception as e:
            return {"error": f"Failed to process file: {str(e)}"}, 500
