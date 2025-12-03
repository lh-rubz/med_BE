from flask import request
from flask_restx import Resource, Namespace, fields
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timezone
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
import requests
import base64
import json
import hashlib
import os
import fitz  # PyMuPDF
from PIL import Image
import io

from models import db, User, Report, ReportField
from config import ollama_client, Config

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
# Note: Using a simple file argument without 'append' for better Swagger compatibility
# Multiple files can still be uploaded by selecting multiple files in the file picker
upload_parser = vlm_ns.parser()
upload_parser.add_argument('file', 
                          location='files',
                          type=FileStorage, 
                          required=True,
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
        description='Upload medical report images or PDF files. Multiple files will be combined into ONE report.',
        responses={
            200: 'Success - Report created',
            400: 'Bad Request - Invalid file or missing data',
            404: 'User not found',
            413: 'File too large'
        }
    )
    @vlm_ns.expect(upload_parser)
    @jwt_required()
    def post(self):
        """Extract medical report data from uploaded image/PDF file(s) and save to database. Multiple images/pages will be combined into a single report."""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        # Debug: Print request info
        print(f"\n{'='*80}")
        print(f"📥 INCOMING REQUEST DEBUG")
        print(f"{'='*80}")
        print(f"Content-Type: {request.content_type}")
        print(f"request.files keys: {list(request.files.keys())}")
        print(f"request.form keys: {list(request.form.keys())}")
        print(f"request.data: {request.data[:200] if request.data else 'None'}")
        print(f"{'='*80}\n")
        
        # Check if file is in request
        if 'file' not in request.files:
            return {
                'error': 'No file part in the request. Please upload a file using form-data with key "file"',
                'debug': {
                    'content_type': request.content_type,
                    'files_keys': list(request.files.keys()),
                    'form_keys': list(request.form.keys())
                }
            }, 400
        
        files = request.files.getlist('file')
        
        if not files or len(files) == 0:
            return {'error': 'No file selected'}, 400

        patient_name = user.first_name + " " + user.last_name
        
        # Create user-specific folder (using user_id for security)
        user_folder = ensure_upload_folder(f"user_{current_user_id}")
        
        # Collect all images to process
        all_images_to_process = []
        saved_files = []
        
        for file in files:
            if file.filename == '':
                continue
                
            if not allowed_file(file.filename):
                return {'error': f'File type not allowed for {file.filename}. Allowed types: {", ".join(Config.ALLOWED_EXTENSIONS)}'}, 400
            
            # Save file with secure filename
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_filename = f"{timestamp}_{filename}"
            file_path = os.path.join(user_folder, unique_filename)
            
            file.save(file_path)
            print(f"✅ File saved to: {file_path}")
            saved_files.append({'filename': filename, 'path': file_path})
            
            # Determine if it's a PDF or image
            file_extension = filename.rsplit('.', 1)[1].lower()
            
            if file_extension == 'pdf':
                print(f"📄 Processing PDF file: {filename}")
                try:
                    images = pdf_to_images(file_path)
                    for page_num, img_data in enumerate(images, 1):
                        all_images_to_process.append({
                            'data': img_data,
                            'format': 'jpeg',  # Already compressed to JPEG
                            'source_filename': filename,
                            'page_number': page_num,
                            'total_pages': len(images)
                        })
                    print(f"✅ Converted PDF to {len(images)} image(s)")
                except Exception as e:
                    print(f"❌ Error converting PDF: {str(e)}")
                    return {'error': f'Failed to process PDF {filename}: {str(e)}'}, 400
            else:
                # It's an image file - compress it
                print(f"🖼️ Processing image file: {filename}")
                with open(file_path, 'rb') as f:
                    image_data = f.read()
                    # Compress the image to reduce payload size
                    compressed_data = compress_image(image_data, file_extension)
                    all_images_to_process.append({
                        'data': compressed_data,
                        'format': 'jpeg',  # Compressed to JPEG
                        'source_filename': filename,
                        'page_number': None,
                        'total_pages': 1
                    })
        
        if not all_images_to_process:
            return {'error': 'No valid image data to process'}, 400
        
        print(f"\n📊 Total images/pages to process: {len(all_images_to_process)}")
        print(f"🔗 Combining all images into ONE report\n")
        
        # Process all images together and create ONE report
        try:
            report_data = self._process_multiple_images(
                all_images_to_process,
                current_user_id,
                user,
                [sf['filename'] for sf in saved_files]
            )
            
            return {
                'message': f'Successfully processed {len(all_images_to_process)} image(s)/page(s) and created 1 report',
                'total_images_processed': len(all_images_to_process),
                'report': report_data
            }, 201
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error processing images: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'error': f'VLM processing error: {str(e)}'}, 500
    
    def _process_multiple_images(self, images_list, current_user_id, user, original_filenames):
        """Process each image separately, then combine all extracted data"""
        patient_name = user.first_name + " " + user.last_name
        
        report_types_list = '\n'.join([f'- "{rt}"' for rt in REPORT_TYPES])
        
        print(f"\n🔄 Processing {len(images_list)} image(s) individually...")
        
        all_extracted_data = []
        patient_info = {}
        
        # Process each image separately
        for idx, image_info in enumerate(images_list, 1):
            print(f"\n{'='*80}")
            print(f"📄 Processing Image {idx}/{len(images_list)}: {image_info['source_filename']}")
            print(f"{'='*80}\n")
            
            # Build extraction prompt for single image
            prompt_text = f"""You are a medical lab report analyzer. Extract ALL medical data from this image which is part {idx} of {len(images_list)} of a complete medical report.

EXTRACTION RULES:
1. Extract EVERY test result, measurement, value visible in this image.
2. Identify the REPORT TYPE from this EXACT list (choose the closest match):
{report_types_list}
3. Extract REFERRING PHYSICIAN names ONLY (doctors who ordered/referred the test).
   - DO NOT include template doctors, clinic signatures, or lab directors
   - Only extract doctors specifically associated with THIS patient's case
4. For each result provide: test name, value, unit, normal range, if normal/abnormal.
   - Extract BOTH numeric values (e.g., "13.5 g/dL") AND qualitative results (e.g., "Normal", "NAD", "Negative")
   - "NAD" means "No Abnormality Detected" - treat as normal result
   - For qualitative results, put the assessment in field_value
   - SKIP category headers - only extract tests with actual values
5. Extract the REPORT DATE - the date the report was generated/issued.
   - Look for "Report Date", "Reported on", "Date", "Issue Date"
   - Format as YYYY-MM-DD
6. Count ALL test fields in THIS image.

CRITICAL - "is_normal" FIELD:
- Set "is_normal": true ONLY if "field_value" is STRICTLY within "normal_range"
- Set "is_normal": false if outside range or marked abnormal
- If no range provided, default to true

CRITICAL - DECIMAL PRECISION:
- Read EXACT decimal values (e.g., "15.75" not "15.7")
- Preserve all decimal places visible

CRITICAL - DOCTOR NAMES:
- Extract ONLY REFERRING PHYSICIAN (who ordered the test)
- Read name carefully and spell exactly

RESPONSE FORMAT - Return ONLY valid JSON:
{{
    "patient_name": "Patient name from report",
    "report_date": "YYYY-MM-DD",
    "report_type": "MUST be one of the exact values from the list above",
    "doctor_names": "Referring physician name(s) only, or empty string",
    "total_fields_in_image": <count of test fields in THIS image>,
    "medical_data": [
        {{
            "field_name": "Test Name",
            "field_value": "123.45 OR 'Normal' OR 'NAD'",
            "field_unit": "g/dL or empty",
            "normal_range": "13.5-17.5 or empty",
            "is_normal": true,
            "field_type": "measurement"
        }}
    ]
}}"""
            
            image_base64 = base64.b64encode(image_info['data']).decode('utf-8')
            image_format = image_info['format']
            
            content = [
                {'type': 'text', 'text': prompt_text},
                {
                    'type': 'image_url',
                    'image_url': {'url': f'data:image/{image_format};base64,{image_base64}'}
                }
            ]
            
            try:
                model_name = Config.OLLAMA_MODEL
                
                # Extract from single image
                completion = ollama_client.chat.completions.create(
                    model=model_name,
                    messages=[{'role': 'user', 'content': content}],
                    temperature=0.1,
                )

                response_text = completion.choices[0].message.content.strip()
                print(f"🔍 RAW RESPONSE for Image {idx}:")
                print("="*80)
                print(response_text)
                print("="*80 + "\n")
                
                extracted_data = None
                try:
                    extracted_data = json.loads(response_text)
                except json.JSONDecodeError as e:
                    import re
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        try:
                            extracted_data = json.loads(json_match.group())
                            print(f"✅ JSON extracted after regex for Image {idx}")
                        except:
                            pass
                    
                    if not extracted_data:
                        print(f"❌ Failed to parse Image {idx}: {e}")
                        continue
                
                if not isinstance(extracted_data, dict):
                    print(f"❌ Invalid response structure for Image {idx}")
                    continue
                
                # Store patient info from first valid extraction
                if not patient_info and extracted_data.get('patient_name'):
                    patient_info = {
                        'patient_name': extracted_data.get('patient_name', ''),
                        'report_date': extracted_data.get('report_date', ''),
                        'report_type': extracted_data.get('report_type', ''),
                        'doctor_names': extracted_data.get('doctor_names', '')
                    }
                
                # Collect medical data
                medical_data = extracted_data.get('medical_data', [])
                if medical_data:
                    all_extracted_data.extend(medical_data)
                    print(f"✅ Extracted {len(medical_data)} field(s) from Image {idx}\n")
                else:
                    print(f"⚠️  No medical data found in Image {idx}\n")
                    
            except Exception as e:
                print(f"❌ Error processing Image {idx}: {e}\n")
                continue
        
        # Combine all extracted data
        print("\n" + "="*80)
        print("🔗 COMBINING ALL EXTRACTED DATA")
        print("="*80)
        
        extracted_data = {
            'patient_name': patient_info.get('patient_name', ''),
            'report_date': patient_info.get('report_date', ''),
            'report_type': patient_info.get('report_type', ''),
            'doctor_names': patient_info.get('doctor_names', ''),
            'total_fields_in_report': len(all_extracted_data),
            'medical_data': all_extracted_data
        }
        
        print(f"✅ Total fields extracted: {len(all_extracted_data)}")
        print(json.dumps(extracted_data, indent=2))
        print("="*80 + "\n")
        
        # SELF-VERIFICATION PASS
        print("\n" + "="*80)
        print("🔄 STARTING SELF-VERIFICATION PASS...")
        print("="*80)
        
        verification_prompt = f"""You extracted data from {len(images_list)} medical report images individually. Review the COMBINED extraction for accuracy:

COMBINED EXTRACTION:
{json.dumps(extracted_data, indent=2)}

Review checklist:
1. Are "is_normal" flags correct? (value within normal_range = true, outside = false)
2. Do field_value numbers have proper decimal precision?
3. Are doctor_names spelled correctly?
4. Does report_type match one of the standard types exactly?
5. Are there duplicate entries that should be merged?
6. Are there any obvious errors or inconsistencies?

RETURN THE CORRECTED JSON in the EXACT same format. If everything is correct, return the same JSON unchanged.

IMPORTANT:
- Only return valid JSON, no explanations
- Keep the same structure
- Fix any inaccuracies you notice
- Remove duplicates if any"""
        
        try:
            verification_completion = ollama_client.chat.completions.create(
                model=model_name,
                messages=[{'role': 'user', 'content': verification_prompt}],
                temperature=0.1,
            )
            
            verified_response = verification_completion.choices[0].message.content.strip()
            print("\n✅ VERIFIED RESPONSE:")
            print("="*80)
            print(verified_response)
            print("="*80 + "\n")
            
            try:
                verified_data = json.loads(verified_response)
                print("✅ Verification successful - using verified data")
                extracted_data = verified_data
            except json.JSONDecodeError:
                import re
                json_match = re.search(r'\{.*\}', verified_response, re.DOTALL)
                if json_match:
                    try:
                        verified_data = json.loads(json_match.group())
                        print("✅ Verification successful (after regex)")
                        extracted_data = verified_data
                    except:
                        print("⚠️  Using original combined data")
                else:
                    print("⚠️  Using original combined data")
                    
        except Exception as verify_error:
            print(f"⚠️  Verification error: {verify_error}")
            print("Using original combined data")
            
            print("\n" + "="*80)
            print("📊 FINAL EXTRACTED DATA:")
            print("="*80)
            print(json.dumps(extracted_data, indent=2))
            print("="*80 + "\n")
            
            # Verify field count
            medical_data_list = extracted_data.get('medical_data', [])
            total_fields_claimed = extracted_data.get('total_fields_in_report', 0)
            actual_extracted = len(medical_data_list)
            
            print("\n" + "="*80)
            print("🔍 FIELD COUNT VERIFICATION:")
            print("="*80)
            print(f"Total fields claimed by VLM: {total_fields_claimed}")
            print(f"Fields actually extracted: {actual_extracted}")
            
            if total_fields_claimed > 0 and actual_extracted < total_fields_claimed:
                missing_count = total_fields_claimed - actual_extracted
                print(f"⚠️  WARNING: {missing_count} field(s) may be missing!")
            elif actual_extracted >= total_fields_claimed:
                print("✅ All fields appear to be extracted")
            print("="*80 + "\n")
            
            medical_data_list = extracted_data.get('medical_data', [])
            
            # Check for duplicates
            if len(medical_data_list) > 0:
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
                            raise Exception(f'This report appears to be a duplicate of an existing report (#{existing_report.id})')
            
            # Save to database
            medical_data_str = json.dumps(medical_data_list, sort_keys=True)
            report_hash = hashlib.sha256(medical_data_str.encode()).hexdigest()
            first_filename = original_filenames[0] if original_filenames else "unknown"
            
            new_report = Report(
                user_id=current_user_id,
                report_date=datetime.now(timezone.utc),
                report_hash=report_hash,
                report_type=extracted_data.get('report_type', 'General Medical Report'),
                doctor_names=extracted_data.get('doctor_names', ''),
                original_filename=first_filename
            )
            db.session.add(new_report)
            db.session.flush()
            
            medical_entries = []
            for item in medical_data_list:
                if not isinstance(item, dict):
                    continue
                
                field = ReportField(
                    report_id=new_report.id,
                    user_id=current_user_id,
                    field_name=str(item.get('field_name', 'Unknown')),
                    field_value=str(item.get('field_value', '')),
                    field_unit=str(item.get('field_unit', '')),
                    normal_range=str(item.get('normal_range', '')),
                    is_normal=bool(item.get('is_normal', True)),
                    field_type=str(item.get('field_type', 'measurement')),
                    notes=str(item.get('notes', ''))
                )
                db.session.add(field)
                db.session.flush()
                
                medical_entries.append({
                    'id': field.id,
                    'field_name': field.field_name,
                    'field_value': field.field_value,
                    'field_unit': field.field_unit,
                    'normal_range': field.normal_range,
                    'is_normal': field.is_normal,
                    'field_type': field.field_type,
                    'notes': field.notes
                })
            
            db.session.commit()
            
            return {
                'report_id': new_report.id,
                'patient_name': extracted_data.get('patient_name', ''),
                'report_date': extracted_data.get('report_date', ''),
                'report_type': new_report.report_type,
                'doctor_names': new_report.doctor_names,
                'original_filename': new_report.original_filename,
                'total_images': len(images_list),
                'source_files': original_filenames,
                'medical_data': medical_entries,
                'total_fields_extracted': len(medical_entries)
            }
            
        except Exception as e:
            print(f"\n❌ ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
