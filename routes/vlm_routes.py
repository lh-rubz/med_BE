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

# API Models
upload_parser = vlm_ns.parser()
upload_parser.add_argument('file', 
                          location='files',
                          type=FileStorage, 
                          required=True,
                          help='Medical report image or PDF file')


def allowed_file(filename):
    """Check if file has an allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def ensure_upload_folder(user_identifier):
    """Create user-specific upload folder if it doesn't exist"""
    user_folder = os.path.join(Config.UPLOAD_FOLDER, str(user_identifier))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder


def pdf_to_images(pdf_path):
    """Convert PDF to images using PyMuPDF"""
    images = []
    pdf_document = fitz.open(pdf_path)
    
    for page_num in range(len(pdf_document)):
        page = pdf_document[page_num]
        # Render page to an image with high quality
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for better quality
        img_data = pix.tobytes("png")
        images.append(img_data)
    
    pdf_document.close()
    return images


@vlm_ns.route('/chat')
class ChatResource(Resource):
    @vlm_ns.doc(security='Bearer Auth')
    @vlm_ns.expect(upload_parser)
    @jwt_required()
    def post(self):
        """Extract medical report data from uploaded image/PDF file and save to database"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        # Check if file is in request
        if 'file' not in request.files:
            return {'error': 'No file part in the request. Please upload a file using form-data with key "file"'}, 400
        
        file = request.files['file']
        
        if file.filename == '':
            return {'error': 'No file selected'}, 400
        
        if not allowed_file(file.filename):
            return {'error': f'File type not allowed. Allowed types: {", ".join(Config.ALLOWED_EXTENSIONS)}'}, 400

        patient_name = user.first_name + " " + user.last_name
        
        # Create user-specific folder (using user_id for security)
        user_folder = ensure_upload_folder(f"user_{current_user_id}")
        
        # Save file with secure filename
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{timestamp}_{filename}"
        file_path = os.path.join(user_folder, unique_filename)
        
        file.save(file_path)
        print(f"✅ File saved to: {file_path}")
        
        # Determine if it's a PDF or image
        file_extension = filename.rsplit('.', 1)[1].lower()
        
        # Process the file
        image_data_list = []
        
        if file_extension == 'pdf':
            print("📄 Processing PDF file...")
            try:
                images = pdf_to_images(file_path)
                for img_data in images:
                    image_data_list.append({
                        'data': img_data,
                        'format': 'png'
                    })
                print(f"✅ Converted PDF to {len(images)} image(s)")
            except Exception as e:
                print(f"❌ Error converting PDF: {str(e)}")
                return {'error': f'Failed to process PDF: {str(e)}'}, 400
        else:
            # It's an image file
            print(f"🖼️ Processing image file ({file_extension})...")
            with open(file_path, 'rb') as f:
                image_data = f.read()
                image_data_list.append({
                    'data': image_data,
                    'format': file_extension
                })
        
        # Process the first image/page (you can extend this to process multiple pages)
        if not image_data_list:
            return {'error': 'No valid image data to process'}, 400
        
        image_info = image_data_list[0]
        image_base64 = base64.b64encode(image_info['data']).decode('utf-8')
        image_format = image_info['format']
        
        report_types_list = '\n'.join([f'- "{rt}"' for rt in REPORT_TYPES])
        
        extraction_prompt = f"""You are a medical lab report analyzer. Extract ALL medical data from this report image.

EXTRACTION RULES:
1. Extract EVERY test result, measurement, value visible in the image.
2. Identify the REPORT TYPE from this EXACT list (choose the closest match):
{report_types_list}
3. Extract REFERRING PHYSICIAN names ONLY (doctors who ordered/referred the test).
   - DO NOT include template doctors, clinic signatures, or lab directors
   - Only extract doctors specifically associated with THIS patient's case
   - If no referring physician is mentioned, leave empty
4. For each result provide: test name, value, unit, normal range, if normal/abnormal.
   - Extract BOTH numeric values (e.g., "13.5 g/dL") AND qualitative results (e.g., "Normal", "NAD", "Negative")
   - "NAD" means "No Abnormality Detected" - treat as normal result
   - Include visual acuity, system examinations, mental status, and all other assessments
   - For qualitative results, put the assessment in field_value (e.g., "Normal", "NAD", "Absent")
   - SKIP category headers (e.g., "DIFFERENTIAL LEUCOCYTE COUNT", "HAEMATOLOGY") - only extract tests with actual values
   - Extract individual sub-tests (e.g., Neutrophils, Lymphocytes) not their parent category
5. Extract the REPORT DATE - this is the date the report was generated/issued.
   - Look for labels like "Report Date", "Reported on", "Date", "Issue Date"
   - DO NOT confuse with collection date, registration date, or patient birth date
   - Format as YYYY-MM-DD
6. Read carefully and extract EXACT values from the image with full decimal precision.

CRITICAL - "is_normal" FIELD:
- Set "is_normal": true ONLY if the "field_value" is STRICTLY within the "normal_range".
- Set "is_normal": false if the value is outside the range (High/Low) or explicitly marked as abnormal.
- If no range is provided, default to true.

CRITICAL - DECIMAL PRECISION:
- Read EXACT decimal values from the image as shown (e.g., "15.75" not "15.7" or "12.5")
- Preserve all decimal places visible in the image
- Double-check each number character-by-character

CRITICAL - DOCTOR NAMES:
- Extract ONLY the REFERRING PHYSICIAN (doctor who ordered the test)
- DO NOT extract examining doctors, lab directors, or clinic signatures
- Only include doctors specifically tied to this patient's case
- Read the name carefully from the image and spell it exactly
- If multiple referring doctors, separate with commas

CRITICAL - HANDLING DIFFERENT VALUE TYPES:
- Numeric values: Extract with full precision (e.g., "15.75")
- Qualitative values: Extract exactly as shown (e.g., "Normal", "NAD", "Negative", "Absent")
- "NAD" = "No Abnormality Detected" = Normal result (set is_normal: true)
- For "NAD" results, put "NAD" in field_value and leave normal_range empty

RESPONSE FORMAT - Return ONLY valid JSON:
{{
    "patient_name": "Patient name from report",
    "report_date": "YYYY-MM-DD (the date report was issued, NOT collection/birth date)",
    "report_type": "MUST be one of the exact values from the list above",
    "doctor_names": "Referring physician name(s) only, or empty string",
    "total_fields_in_report": <count of all test fields you see>,
    "medical_data": [
        {{
            "field_name": "Test Name",
            "field_value": "123.45 OR 'Normal' OR 'NAD' OR 'Negative'",
            "field_unit": "g/dL or empty for qualitative results",
            "normal_range": "13.5-17.5 or empty",
            "is_normal": true,
            "field_type": "measurement"
        }}
    ]
}}

RULES:
- Response must be ONLY valid JSON
- Extract ALL visible fields
- medical_data array can be empty if none found
- Use empty strings for missing values
- report_type MUST match one of the provided options exactly"""

        try:
            # Image data is already loaded from file
            content = [
                {
                    'type': 'text',
                    'text': extraction_prompt
                },
                {
                    'type': 'image_url',
                    'image_url': {
                        'url': f'data:image/{image_format};base64,{image_base64}'
                    }
                }
            ]
        except Exception as e:
            print(f"\n❌ ERROR processing image: {str(e)}")
            return {
                'message': 'Failed to process image',
                'error': str(e)
            }, 400

        try:
            model_name = Config.OLLAMA_MODEL
            completion = ollama_client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        'role': 'user',
                        'content': content
                    }
                ],
                temperature=0.1,
            )

            response_text = completion.choices[0].message.content.strip()
            print("\n" + "="*80)
            print("🔍 MODEL SERVER RAW RESPONSE (FIRST PASS):")
            print("="*80)
            print(response_text)
            print("="*80 + "\n")
            
            extracted_data = None
            try:
                extracted_data = json.loads(response_text)
                print("\n" + "="*80)
                print("✅ PARSED JSON DATA:")
                print("="*80)
                print(json.dumps(extracted_data, indent=2))
                print("="*80 + "\n")
            except json.JSONDecodeError as e:
                print("\n" + "="*80)
                print("❌ JSON PARSE ERROR:")
                print("="*80)
                print(f"Error: {e}")
                print(f"Response was: {response_text[:200]}...")
                print("="*80 + "\n")
                
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        extracted_data = json.loads(json_match.group())
                        print("✅ JSON extracted from response after regex match")
                    except:
                        extracted_data = None
                
                if not extracted_data:
                    print("❌ Could not parse VLM response as JSON - aborting extraction")
                    return {
                        'message': 'Failed to parse medical report',
                        'error': 'Invalid response format',
                        'details': f'JSON parse error: {str(e)}'
                    }, 400
            
            if not isinstance(extracted_data, dict):
                print("❌ Invalid response structure - not a dictionary")
                return {
                    'message': 'Failed to parse medical report',
                    'error': 'Invalid response structure'
                }, 400
            
            if 'medical_data' not in extracted_data:
                extracted_data['medical_data'] = []
            if 'patient_name' not in extracted_data:
                extracted_data['patient_name'] = ''
            
            # SELF-VERIFICATION PASS
            print("\n" + "="*80)
            print("🔄 STARTING SELF-VERIFICATION PASS...")
            print("="*80)
            
            verification_prompt = f"""You are reviewing a medical report extraction that you just performed.

ORIGINAL EXTRACTION:
{json.dumps(extracted_data, indent=2)}

Your task is to:
1. Review the extracted data for accuracy
2. Check if "is_normal" flags are correct based on values vs normal ranges
3. CRITICAL: Verify all field_value numbers have EXACT decimal precision from the image (e.g., 15.75 not 12.5)
4. CRITICAL: Verify doctor_names are spelled correctly and match the image exactly
5. Ensure report_type matches one of the standard types
6. Correct any errors you find

RETURN THE CORRECTED JSON in the EXACT same format. If everything is correct, return the same JSON.

IMPORTANT:
- Only return valid JSON
- Keep the same structure
- Fix any inaccuracies you notice
- Pay special attention to decimal values and doctor names"""
            
            try:
                verification_completion = ollama_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            'role': 'user',
                            'content': [
                                {'type': 'text', 'text': verification_prompt},
                                {
                                    'type': 'image_url',
                                    'image_url': {
                                        'url': f'data:image/{image_format};base64,{image_base64}'
                                    }
                                }
                            ]
                        }
                    ],
                    temperature=0.1,
                )
                
                verified_response = verification_completion.choices[0].message.content.strip()
                print("\n" + "="*80)
                print("✅ VERIFIED RESPONSE (SECOND PASS):")
                print("="*80)
                print(verified_response)
                print("="*80 + "\n")
                
                # Try to parse verified response
                try:
                    verified_data = json.loads(verified_response)
                    print("✅ Verification pass successful - using verified data")
                    extracted_data = verified_data
                except json.JSONDecodeError:
                    # Try regex extraction
                    import re
                    json_match = re.search(r'\{.*\}', verified_response, re.DOTALL)
                    if json_match:
                        try:
                            verified_data = json.loads(json_match.group())
                            print("✅ Verification pass successful (after regex) - using verified data")
                            extracted_data = verified_data
                        except:
                            print("⚠️  Verification pass failed to parse - using original extraction")
                    else:
                        print("⚠️  Verification pass failed to parse - using original extraction")
                        
            except Exception as verify_error:
                print(f"⚠️  Verification pass error: {verify_error}")
                print("Using original extraction")
            
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
            print(f"Total fields in report (VLM count): {total_fields_claimed}")
            print(f"Fields actually extracted: {actual_extracted}")
            
            if total_fields_claimed > 0 and actual_extracted < total_fields_claimed:
                missing_count = total_fields_claimed - actual_extracted
                print(f"⚠️  WARNING: {missing_count} field(s) may be missing!")
                print("   The VLM will re-verify in the second pass.")
            elif actual_extracted >= total_fields_claimed:
                print("✅ All fields appear to be extracted")
            print("="*80 + "\n")
            
            medical_data_list = extracted_data.get('medical_data', [])
            
            if len(medical_data_list) > 0:
                existing_reports = Report.query.filter_by(user_id=current_user_id).all()
                
                print("\n" + "="*80)
                print("🔍 CHECKING FOR DUPLICATES:")
                print("="*80)
                print(f"New report has {len(medical_data_list)} fields")
                print(f"Comparing against {len(existing_reports)} existing reports...\n")
                
                new_field_map = {}
                for item in medical_data_list:
                    field_name = str(item.get('field_name', '')).lower().strip()
                    field_value = str(item.get('field_value', '')).strip()
                    new_field_map[field_name] = field_value
                
                for existing_report in existing_reports:
                    existing_fields = ReportField.query.filter_by(report_id=existing_report.id).all()
                    existing_field_map = {}
                    for field in existing_fields:
                        field_name = str(field.field_name).lower().strip()
                        field_value = str(field.field_value).strip()
                        existing_field_map[field_name] = field_value
                    
                    if existing_field_map:
                        matching_fields = 0
                        for field_name, field_value in new_field_map.items():
                            if field_name in existing_field_map and existing_field_map[field_name] == field_value:
                                matching_fields += 1
                        
                        match_percentage = (matching_fields / len(new_field_map)) * 100 if new_field_map else 0
                        
                        print(f"Report #{existing_report.id}: {match_percentage:.1f}% match ({matching_fields}/{len(new_field_map)} fields)")
                        
                        if match_percentage >= 90:
                            print(f"⚠️ HIGH MATCH DETECTED ({match_percentage:.1f}%)")
                            return {
                                'message': 'This report appears to be a duplicate of an existing report',
                                'error': 'Possible duplicate',
                                'existing_report_id': existing_report.id,
                                'existing_report_date': str(existing_report.created_at),
                                'match_percentage': match_percentage,
                                'matching_fields': matching_fields,
                                'total_new_fields': len(new_field_map)
                            }, 409
                
                print("✅ No duplicates found - Report is unique\n")
                print("="*80 + "\n")
            
            try:
                medical_data_str = json.dumps(medical_data_list, sort_keys=True)
                report_hash = hashlib.sha256(medical_data_str.encode()).hexdigest()
                
                new_report = Report(
                    user_id=current_user_id,
                    report_date=datetime.now(timezone.utc),
                    report_hash=report_hash,
                    report_type=extracted_data.get('report_type', 'General Medical Report'),
                    doctor_names=extracted_data.get('doctor_names', ''),
                    original_filename=filename
                )
                db.session.add(new_report)
                db.session.flush()
                
                medical_entries = []
                
                print("\n" + "="*80)
                print(f"📊 PROCESSING {len(medical_data_list)} MEDICAL FIELDS:")
                print("="*80)
                
                for i, item in enumerate(medical_data_list):
                    print(f"\n[Field {i+1}]:")
                    print(json.dumps(item, indent=2))
                    
                    if not isinstance(item, dict):
                        print(f"⚠️ Skipping non-dict item: {item}")
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
                
                print("="*80)
                print(f"✅ Successfully added {len(medical_entries)} fields to database")
                print("="*80 + "\n")
                
                db.session.commit()
                
                return {
                    'message': 'Report extracted and saved successfully',
                    'report_id': new_report.id,
                    'patient_name': extracted_data.get('patient_name', ''),
                    'report_date': extracted_data.get('report_date', ''),
                    'report_type': new_report.report_type,
                    'doctor_names': new_report.doctor_names,
                    'original_filename': new_report.original_filename,
                    'medical_data': medical_entries,
                    'total_fields_extracted': len(medical_entries)
                }, 201
                
            except Exception as e:
                db.session.rollback()
                print(f"\n❌ ERROR saving to database: {str(e)}")
                import traceback
                traceback.print_exc()
                return {
                    'message': 'Failed to save report data',
                    'error': str(e)
                }, 500
                
        except Exception as e:
            print(f"\n❌ VLM PROCESSING ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'error': f'VLM processing error: {str(e)}'}, 500
