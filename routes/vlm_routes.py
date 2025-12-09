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

from models import db, User, Report, ReportField, ReportFile, MedicalSynonym
from config import ollama_client, Config
from utils.medical_validator import validate_medical_data, MedicalValidator
from utils.ocr_extractor import get_ocr_instance
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
        # Render page to an image with 1.5x zoom (balanced quality/size)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
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
    
    # Resize if image is very large (max 2000px on longest side)
    max_dimension = 2000
    if max(img.size) > max_dimension:
        ratio = max_dimension / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        print(f"  ↓ Resized image from {image_data.__sizeof__()} to fit {max_dimension}px")
    
    # Compress to JPEG with quality 85 (good balance)
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=85, optimize=True)
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
        
        if not files or len(files) == 0:
            return {'error': 'No file selected'}, 400

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
                yield from self._process_multiple_images_stream(all_images_to_process, current_user_id, user, saved_files)
                
            except Exception as e:
                print(f"Stream Error: {e}")
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'error': f'Server Error: {str(e)}'})}\n\n"

        return Response(stream_with_context(generate_progress()), content_type='text/event-stream')

    def _process_multiple_images_stream(self, images_list, current_user_id, user, saved_files):
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
            
            # Step 1: OCR
            yield f"data: {json.dumps({'percent': current_progress, 'message': f'Reading text from page {idx} of {total_pages}...'})}\n\n"
            print(f"📝 Step 1: Extracting text with OCR...")
            
            ocr_text = None
            try:
                ocr = get_ocr_instance(languages=['ar', 'en'])
                ocr_text = ocr.extract_text(image_info['data'])
                print(f"✅ OCR extracted {len(ocr_text)} characters")
                print(f"📄 OCR Text Preview:\n{ocr_text[:300]}...\n")
            except Exception as e:
                print(f"⚠️  OCR failed: {e}, using image-only mode")
            
            # Step 2: VLM
            print(f"🤖 Step 2: Structuring data with VLM (hybrid mode)...")
            yield f"data: {json.dumps({'percent': current_progress + 10, 'message': f'Understanding medical values on page {idx}...'})}\n\n"
            
            # Build prompt (Reusing logic)
            # Build OPTIMIZED extraction prompt (reduced by ~40%)
            prompt_text = f"""Extract ALL medical data from this image (page {idx}/{total_pages}).

RULES:
1. Extract EVERY test with its value, unit, normal range. Skip headers.
2. Report Identification:
   - report_name: Extract the EXACT title written on the report (e.g., "Detailed Hemogram", "Lipid Profile"). If no title, use "Medical Report".
   - report_type: Choose the CLOSEST match from this standard list: {', '.join(REPORT_TYPES)}. If no good match, use "Other".
3. IMPORTANT - Extract doctor names:
   - Look for "Ref. By:", "Ref By:", "Referred By:", "Referring Doctor:", or "Dr." followed by a name
   - Extract the FULL name (e.g., "Dr. Hiren Shah" → "Hiren Shah", "Dr. M. Patel" → "M. Patel")
   - Include middle initials if present
   - If multiple doctors, separate with commas
   - CRITICAL: Do NOT leave empty - if you see ANY doctor name on the report, extract it
4. Preserve EXACT decimal precision (e.g., "15.75" not "15.7")
5. For qualitative results ("Normal", "NAD", "Negative"), put in field_value
6. Extract report date as YYYY-MM-DD
7. Extract patient details:
   - patient_age: Extract age if found (e.g. "45", "45 Y", "45 Years"). If not found, use null or empty string.
   - patient_gender: Extract gender if found (e.g. "Male", "Female", "M", "F"). Expand "M"/"F" to full words.
8. If value marked "High" or "Low", add to notes
9. IMPORTANT - Extract normal_range WITHOUT units:
   - Remove units from range (e.g., "12 - 16 g/dL" → "12 - 16")
   - Keep only the numeric range values
   - For text ranges (e.g., "Normal: <5.7"), keep the text but remove units
9. IMPORTANT - Extract category/section for EACH test:
   - Look for section headers like "DIFFERENTIAL COUNT", "BLOOD INDICES", "ABSOLUTE COUNT", "WBC COUNT", "PLATELET COUNT"
   - Assign each test to its category (use exact header text in UPPERCASE)
   - If no category header visible, use empty string

Return ONLY valid JSON:
{{
    "patient_name": "...",
    "patient_age": "...",
    "patient_gender": "...",
    "patient_gender": "...",
    "report_date": "YYYY-MM-DD",
    "report_name": "...",
    "report_type": "...",
    "doctor_names": "...",
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
                
                content = []
                if ocr_text:
                     enhanced_prompt = f"{prompt_text}\n\nIMPORTANT: I've also extracted the text using OCR below. Use this OCR text for ACCURATE Arabic character recognition.\n\nOCR EXTRACTED TEXT:\n{ocr_text}"
                     content.append({'type': 'text', 'text': enhanced_prompt})
                else:
                     content.append({'type': 'text', 'text': prompt_text})
                
                content.append({
                    'type': 'image_url',
                    'image_url': {'url': f'data:image/{image_format};base64,{image_base64}'}
                })
                
                completion = ollama_client.chat.completions.create(
                    model=Config.OLLAMA_MODEL,
                    messages=[{'role': 'user', 'content': content}],
                    temperature=0.1
                )
                response_text = completion.choices[0].message.content.strip()
                print(f"🔍 RAW RESPONSE for Image {idx}:\n{'-'*40}\n{response_text[:300]}...\n{'-'*40}")
                
                # Parsing logic
                extracted_data = {}
                try:
                    import re
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        extracted_data = json.loads(json_match.group())
                        print(f"✅ JSON extracted after regex for Image {idx}")
                except:
                    pass
                
                if extracted_data.get('medical_data'):
                    all_extracted_data.extend(extracted_data['medical_data'])
                    print(f"✅ Extracted {len(extracted_data['medical_data'])} field(s) from page {idx}")
                
                # Capture patient info from first good page
                if not patient_info and extracted_data.get('patient_name'):
                     patient_info = extracted_data

                print(f"✅ Page {idx} Analysis Complete. Found {len(extracted_data.get('medical_data', []))} data points.")
                     
            except Exception as e:
                print(f"❌ VLM Error on page {idx}: {e}")

        # Step 3: Validation
        yield f"data: {json.dumps({'percent': 75, 'message': 'Double-checking the results...'})}\n\n"
        print(f"🔍 Validating aggregated data ({len(all_extracted_data)} total items)...")
        
        # Combine data
        final_data = {
            'patient_name': patient_info.get('patient_name', ''),
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
                    # Known alias -> Use standard name
                    print(f"   ✓ Normalized: '{original_name}' -> '{synonym_record.standard_name}'")
                    item['field_name'] = synonym_record.standard_name
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
                    
                    client = Client(host=Config.OLLAMA_BASE_URL)
                    # Using the larger model as requested by user, but batched for speed
                    response = client.chat(model='gemma3:12b', messages=[
                        {'role': 'user', 'content': learning_prompt}
                    ])
                    
                    response_text = response['message']['content'].strip()
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
                                
                            # Update items in the list
                            for item in medical_data_list:
                                if item.get('field_name') == original:
                                    item['field_name'] = standardized
                                    
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

        # Step 4: Duplicate Check
        yield f"data: {json.dumps({'percent': 85, 'message': 'Ensuring this is a new report...'})}\n\n"
        
        try:
            medical_data_list = final_data.get('medical_data', [])
            if len(medical_data_list) > 0:
                extracted_date_str = final_data.get('report_date')
                existing_reports = []
                
                # Filter reports by date for optimization
                if extracted_date_str and len(extracted_date_str) == 10:  # YYYY-MM-DD
                    try:
                        target_date = datetime.strptime(extracted_date_str, '%Y-%m-%d').date()
                        start_of_day = datetime.combine(target_date, datetime.min.time())
                        end_of_day = datetime.combine(target_date, datetime.max.time())
                        
                        existing_reports = Report.query.filter(
                            Report.user_id == current_user_id,
                            Report.report_date >= start_of_day,
                            Report.report_date <= end_of_day
                        ).all()
                    except ValueError:
                        existing_reports = Report.query.filter_by(user_id=current_user_id).all()
                else:
                    existing_reports = Report.query.filter_by(user_id=current_user_id).all()
                
                new_field_map = {str(item.get('field_name', '')).lower().strip(): str(item.get('field_value', '')).strip() 
                                 for item in medical_data_list}
                
                for existing_report in existing_reports:
                    existing_fields = ReportField.query.filter_by(report_id=existing_report.id).all()
                    existing_field_map = {str(field.field_name).lower().strip(): str(field.field_value).strip() 
                                          for field in existing_fields}
                    
                    if existing_field_map:
                        matching_fields = sum(1 for fn, fv in new_field_map.items() 
                                              if fn in existing_field_map and existing_field_map[fn] == fv)
                        match_percentage = (matching_fields / len(new_field_map)) * 100 if new_field_map else 0
                        
                        if match_percentage >= 90:
                             error_msg = f'This report appears to be a duplicate of an existing report (#{existing_report.id})'
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
            
            new_report = Report(
                user_id=current_user_id,
                report_date=datetime.now(timezone.utc),
                report_hash=report_hash,
                report_name=final_data.get('report_name'),
                report_type=final_data.get('report_type'),
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
            
            # Final Success Payload
            success_payload = {
                'percent': 100, 
                'message': 'Analysis Completed!', 
                'report_id': new_report.id,
                'patient_name': final_data.get('patient_name', ''),
                'patient_age': new_report.patient_age,
                'patient_gender': new_report.patient_gender,
                'report_date': final_data.get('report_date', ''),
                'report_name': new_report.report_name,
                'report_type': new_report.report_type,
                'doctor_names': new_report.doctor_names,
                'original_filename': new_report.original_filename,
                'total_images': len(images_list),
                'source_files': [sf['original_filename'] for sf in saved_files],
                'medical_data': medical_entries,
                'total_fields_extracted': len(medical_entries)
            }
            print(f"✅ SUCCESS: Report #{new_report.id} created with {len(medical_entries)} fields.")
            yield f"data: {json.dumps(success_payload)}\n\n"
            
        except Exception as e:
            db.session.rollback()
            yield f"data: {json.dumps({'error': f'❌ Database Error: {str(e)}'})}\n\n"
