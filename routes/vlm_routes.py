from flask import request
from flask_restx import Resource, Namespace, fields
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timezone
import requests
import base64
import json
import hashlib
import os

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
report_extraction_model = vlm_ns.model('ReportExtraction', {
    'image_url': fields.String(required=True, description='URL to medical report image for extraction')
})


@vlm_ns.route('/chat')
class ChatResource(Resource):
    @vlm_ns.doc(security='Bearer Auth')
    @jwt_required()
    @vlm_ns.expect(report_extraction_model)
    def post(self):
        """Extract medical report data and save to database"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        data = request.json or {}
        image_url = data.get('image_url')
        
        if not image_url:
            return {'error': 'image_url is required for report extraction'}, 400

        patient_name = user.first_name + " " + user.last_name
        
        report_types_list = '\n'.join([f'- "{rt}"' for rt in REPORT_TYPES])
        
        extraction_prompt = f"""You are a medical lab report analyzer. Extract ALL medical data from this report.

EXTRACTION RULES:
1. Extract EVERY test result, measurement, value visible.
2. Identify the REPORT TYPE from this EXACT list (choose the closest match):
{report_types_list}
3. Extract REFERRING PHYSICIAN names ONLY (doctors who ordered/referred the test).
   - DO NOT include template doctors, clinic signatures, or lab directors
   - Only extract doctors specifically associated with THIS patient's case
   - If no referring physician is mentioned, leave empty
4. For each result provide: test name, value, unit, normal range, if normal/abnormal.
5. Extract report date if available.

CRITICAL - "is_normal" FIELD:
- Set "is_normal": true ONLY if the "field_value" is STRICTLY within the "normal_range".
- Set "is_normal": false if the value is outside the range (High/Low) or explicitly marked as abnormal.
- If no range is provided, default to true.

CRITICAL - DECIMAL PRECISION:
- Preserve EXACT decimal values as shown in the report
- If a value shows "15.75", write "15.75" NOT "15.7" or "12.5"
- Copy numbers character-by-character from the image

CRITICAL - DOCTOR NAMES:
- Extract ONLY the REFERRING PHYSICIAN (doctor who ordered the test)
- DO NOT extract template doctors, lab directors, or clinic signatures
- Only include doctors specifically tied to this patient's case
- Double-check spelling and titles (Dr., Prof., etc.)
- If multiple referring doctors, separate with commas

RESPONSE FORMAT - Return ONLY valid JSON:
{{
    "patient_name": "Patient name from report",
    "report_date": "YYYY-MM-DD or empty",
    "report_type": "MUST be one of the exact values from the list above",
    "doctor_names": "Referring physician name(s) only, or empty string",
    "medical_data": [
        {{
            "field_name": "Test Name",
            "field_value": "123.45",
            "field_unit": "g/dL",
            "normal_range": "13.5-17.5",
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
            session = requests.Session()
            img_response = session.get(image_url, timeout=60)
            img_response.raise_for_status()
            
            image_base64 = base64.b64encode(img_response.content).decode('utf-8')
            
            content_type = img_response.headers.get('Content-Type', '')
            if 'jpeg' in content_type or 'jpg' in content_type or image_url.lower().endswith(('.jpg', '.jpeg')):
                image_format = 'jpeg'
            elif 'png' in content_type or image_url.lower().endswith('.png'):
                image_format = 'png'
            elif 'webp' in content_type or image_url.lower().endswith('.webp'):
                image_format = 'webp'
            else:
                from io import BytesIO
                from PIL import Image
                img = Image.open(BytesIO(img_response.content))
                image_format = img.format.lower() if img.format else 'jpeg'
            
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
            print(f"\n❌ ERROR downloading/processing image: {str(e)}")
            return {
                'message': 'Failed to download or process image',
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
                    doctor_names=extracted_data.get('doctor_names', '')
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
