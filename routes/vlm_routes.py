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


from models import db, User, Report, ReportField, ReportFile, MedicalSynonym
from config import ollama_client, Config
from utils.medical_validator import validate_medical_data, MedicalValidator
from utils.medical_mappings import add_new_alias
from utils.vlm_prompts import get_main_vlm_prompt, get_table_retry_prompt, get_personal_info_prompt, get_universal_extraction_prompt
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

def deduplicate_medical_data(medical_data):
    """
    Deduplicate medical data items based on field_name.
    Prioritize items with more complete information (value + range).
    """
    if not medical_data:
        return []
    
    unique_map = {}
    
    for item in medical_data:
        name = item.get('field_name', '').strip()
        if not name:
            continue
            
        # Normalize name for key (lowercase)
        key = name.lower()
        
        if key not in unique_map:
            unique_map[key] = item
        else:
            # Conflict resolution: prefer the one with values/ranges
            existing = unique_map[key]
            
            # Helper to check completeness
            def get_score(itm):
                score = 0
                if itm.get('field_value') and str(itm.get('field_value')).strip() not in ["", "N/A", "n/a"]: score += 2
                if itm.get('normal_range') and str(itm.get('normal_range')).strip() not in ["", "-", "N/A"]: score += 1
                return score
            
            # If new item has better score, replace. If equal, keep existing (usually first one found).
            if get_score(item) > get_score(existing):
                unique_map[key] = item
            
    return list(unique_map.values())


def recalculate_normality(medical_data, patient_gender=None):
    """
    Programmatically recalculate is_normal based on value and range using Robust MedicalValidator.
    """
    if not medical_data:
        return medical_data

    validated_data = []
    for item in medical_data:
        # Use the robust validator from utils
        val_item = MedicalValidator.validate_and_normalize_field(item, patient_gender=patient_gender)
        validated_data.append(val_item)

    return validated_data

def recheck_data_consistency(medical_data, raw_text):
    """
    Recheck data consistency until two consecutive checks produce the same results.
    """
    previous_data = None
    current_data = medical_data

    while previous_data != current_data:
        previous_data = current_data
        corrected_data = verify_and_correct_with_llm(previous_data, raw_text)
        current_data = recalculate_normality(corrected_data)

    return current_data

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


# Initialize EasyOCR reader globally to avoid reloading model on every request
# Added 'ar' for Arabic support
reader = easyocr.Reader(['en', 'ar'])

@vlm_ns.route('/extract-personal-info')
class ExtractPersonalInfo(Resource):
    @jwt_required()
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
            # Use global reader (initialized with 'en' and 'ar') to support Arabic text extraction
            # reader = easyocr.Reader(['en']) - REMOVED to avoid English-only restriction
            
            if uploaded_file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                # Process image file using easyocr
                result = reader.readtext(uploaded_file.read(), detail=0)
                extracted_text = "\n".join(result)
            elif uploaded_file.filename.lower().endswith('.pdf'):
                # Process PDF file - Convert to images for robust OCR
                pdf_document = fitz.open(stream=uploaded_file.read(), filetype="pdf")
                for page_num in range(len(pdf_document)):
                    page = pdf_document[page_num]
                    pix = page.get_pixmap()
                    img_data = pix.tobytes("png")
                    result = reader.readtext(img_data, detail=0)
                    extracted_text += "\n".join(result) + "\n"
            else:
                return {"error": "Unsupported file type. Please upload a PDF or image."}, 400

            # Extract personal information
            extracted_info = extract_personal_info(extracted_text)
            return {"extracted_info": extracted_info}, 200

        except Exception as e:
            return {"error": f"Failed to process file: {str(e)}"}, 500

def generate_prompt_for_page(page_text, page_idx, total_pages):
    """
    Generate a strict and precise prompt for the model based on the page content.
    """
    return f"""
    TASK: Extract medical data from the report page.

    PAGE INDEX: {page_idx}/{total_pages}

    PAGE CONTENT:
    {page_text}

    INSTRUCTIONS:
    1. Extract all medical fields with their values, units, and normal ranges.
    2. Extract patient information if visible (Name, Age, DOB, Gender, Doctor Name).
    3. For each medical field, calculate and set "is_normal" based on the value and range.
    4. Ensure all extracted data is accurate and matches the page content.
    5. Handle both Arabic and English text correctly.
    6. Return the output as a valid JSON object with "patient_info" and "medical_data".

    OUTPUT FORMAT:
    {{
        "patient_info": {{
            "patient_name": "",
            "patient_age": "",
            "patient_dob": "",
            "patient_gender": "",
            "report_date": "",
            "doctor_names": ""
        }},
        "medical_data": [
            {{
                "field_name": "",
                "field_value": "",
                "field_unit": "",
                "normal_range": "",
                "is_normal": true/false/null,
                "notes": ""
            }}
        ]
    }}
    """

def process_page_with_llm(page_text, page_idx, total_pages):
    """
    Process a single page using a three-step strategy (Self-Prompting):
    1. Analyze the page structure (count rows, identify columns).
    2. Generate a custom prompt based on the analysis.
    3. Extract data using the custom prompt.
    """
    debug_logs = []

    # Step 1: Analyze Page Structure
    analysis_result = {}
    try:
        analysis_prompt = get_report_analysis_prompt(page_idx, total_pages)
        debug_logs.append({"step": "1_analysis_prompt", "prompt_preview": analysis_prompt[:100] + "..."})
        
        response_analysis = ollama_client.chat.completions.create(
            model=Config.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": "You are a senior medical report analyst. output valid JSON only."},
                {"role": "user", "content": analysis_prompt + f"\n\nPAGE CONTENT:\n{page_text}"}
            ],
            temperature=0.1,
            max_tokens=4000
        )
        analysis_content = response_analysis.choices[0].message.content.strip()
        
        # Parse Analysis JSON
        if "```json" in analysis_content:
            analysis_content = analysis_content.split("```json")[1].split("```")[0].strip()
        elif "```" in analysis_content:
            analysis_content = analysis_content.split("```")[1].split("```")[0].strip()
            
        analysis_result = json.loads(analysis_content)
        debug_logs.append({"step": "1_analysis_result", "result": analysis_result})
        print(f"  📊 Page {page_idx} Analysis: Found {analysis_result.get('total_test_rows', 'N/A')} rows.")

    except Exception as e:
        print(f"Analysis failed for page {page_idx}: {e}")
        debug_logs.append({"step": "1_analysis_error", "error": str(e)})
        # Fallback to basic prompt if analysis fails
        analysis_result = {}

    # Step 2: Generate Custom Prompt
    try:
        if analysis_result:
            generated_prompt = get_custom_extraction_prompt(analysis_result, page_idx, total_pages)
            generated_prompt += f"\n\nPAGE CONTENT:\n{page_text}"
        else:
            # Fallback
            generated_prompt = generate_prompt_for_page(page_text, page_idx, total_pages)
            
        debug_logs.append({
            "step": "2_generate_prompt",
            "page": page_idx,
            "prompt_preview": generated_prompt[:200] + "..."
        })
    except Exception as e:
        print(f"Prompt generation failed for page {page_idx}: {e}")
        debug_logs.append({"step": "2_generate_prompt_error", "error": str(e)})
        return None, debug_logs

    # Step 3: Extract Data
    try:
        response_extract = ollama_client.chat.completions.create(
            model=Config.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise medical data extractor. Output valid JSON only."},
                {"role": "user", "content": generated_prompt}
            ],
            temperature=0.1,
            max_tokens=4000
        )
        extract_content = response_extract.choices[0].message.content.strip()
        debug_logs.append({
            "step": "3_extraction",
            "page": page_idx,
            "response": extract_content[:200] + "..."
        })

        # Parse Extraction
        if "```json" in extract_content:
            extract_content = extract_content.split("```json")[1].split("```")[0].strip()
        elif "```" in extract_content:
            extract_content = extract_content.split("```")[1].split("```")[0].strip()

        extracted_data = json.loads(extract_content)
        return extracted_data, debug_logs

    except Exception as e:
        print(f"Extraction failed for page {page_idx}: {e}")
        debug_logs.append({"step": "3_extraction_error", "error": str(e)})
        return None, debug_logs




def verify_and_correct_with_llm(extracted_data, raw_text):
    """
    Second pass: Use LLM to verify extracted data against raw text.
    Corrects hallucinations, misaligned values, and swaps.
    """
    if not extracted_data:
        return []

    print("  🕵️ Starting Self-Correction Pass...")
    
    # Context window management
    text_context = raw_text[:30000] # Limit to avoid context overflow
    
    prompt = f"""
    TASK: Verify and Correct Medical Data.
    
    RAW REPORT TEXT:
    {text_context}
    
    EXTRACTED DATA (JSON):
    {json.dumps(extracted_data, ensure_ascii=False)}
    
    INSTRUCTIONS:
    1. Check every field in EXTRACTED DATA against RAW REPORT TEXT.
    2. CORRECTIONS REQUIRED:
       - Fix numerical values (e.g., "5.2" vs "52").
       - Fix units (e.g., "g/L" vs "g/dL").
       - Fix names (Doctor vs Patient).
       - REMOVE hallucinated fields (not in text).
       - ADD missing fields (visible in text but missing in JSON).
    3. RE-EVALUATE "is_normal":
       - true: Value is strictly within Range.
       - false: Value is outside Range.
       - null: No range.
       - The model itself must calculate and set the "is_normal" field based on the value and range.

    OUTPUT:
    - Return ONLY the corrected JSON list of objects.
    """
    
    try:
        response = ollama_client.chat.completions.create(
            model=Config.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise medical data auditor. Output only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=4000
        )
        content = response.choices[0].message.content.strip()
        
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        corrected_data = json.loads(content)
        print(f"  ✅ Self-Correction complete. Items: {len(extracted_data)} -> {len(corrected_data)}")
        return corrected_data
        
    except Exception as e:
        print(f"  ⚠️ Self-Correction failed: {e}")
        return extracted_data


@vlm_ns.route('/chat')
class ChatResource(Resource):
    @jwt_required()
    def post(self):
        """
        Extract personal and medical information from an uploaded medical report file (image or PDF).
        Uses a robust single-pass universal bilingual prompt (Arabic/English).
        """
        if 'file' not in request.files:
            return {"error": "No file uploaded."}, 400

        files = request.files.getlist('file')
        if not files:
            return {"error": "No files provided."}, 400

        try:
            extracted_text_pages = [] # List of (page_num, text_content)
            page_global_idx = 1
            
            # --- STEP 1: ROBUST TEXT EXTRACTION ---
            print("📂 Processing uploaded files...")
            for uploaded_file in files:
                filename = uploaded_file.filename.lower()
                
                if filename.endswith('.pdf'):
                    # Load PDF
                    file_content = uploaded_file.read()
                    pdf_document = fitz.open(stream=file_content, filetype="pdf")
                    
                    for page_num in range(len(pdf_document)):
                        page = pdf_document[page_num]
                        text = page.get_text()
                        
                        # Heuristics to force OCR (Arabic or Scanned)
                        # Check for Arabic characters
                        has_arabic = bool(re.search(r'[\u0600-\u06FF]', text))
                        # Check if page is mostly images
                        has_images = len(page.get_images()) > 0
                        # Check for sparse text (scanned PDF)
                        is_scanned = len(text.strip()) < 100
                        
                        if has_arabic or (is_scanned and has_images):
                            print(f"  📄 Page {page_global_idx}: Detected Arabic/Scanned content. Using OCR.")
                            # Force OCR
                            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                            img_data = pix.tobytes("png")
                            # Use global 'reader' (EasyOCR)
                            # paragraph=True helps preserve table structure
                            result = reader.readtext(img_data, detail=0, paragraph=True)
                            page_text = "\n".join(result)
                        else:
                            print(f"  📄 Page {page_global_idx}: Native Text Extraction.")
                            # Native PDF
                            page_text = text
                            
                        extracted_text_pages.append((page_global_idx, page_text))
                        page_global_idx += 1
                        
                elif filename.endswith(('.png', '.jpg', '.jpeg')):
                    print(f"  🖼️ Image File {page_global_idx}: Using OCR.")
                    # Image OCR
                    file_content = uploaded_file.read()
                    result = reader.readtext(file_content, detail=0, paragraph=True)
                    page_text = "\n".join(result)
                    extracted_text_pages.append((page_global_idx, page_text))
                    page_global_idx += 1
            
            if not extracted_text_pages:
                return {"error": "Could not extract text from files."}, 400

            # --- STEP 2: ANALYZE WITH LLM (Universal Prompt) ---
            print("🤖 Sending to LLM for Analysis...")
            
            aggregated_results = {
                "patient_info": {},
                "medical_tests": []
            }
            
            total_pages = len(extracted_text_pages)
            
            for page_idx, page_content in extracted_text_pages:
                print(f"  🧠 Analyzing Page {page_idx}/{total_pages}...")
                
                prompt = get_universal_extraction_prompt(page_idx, total_pages)
                
                response = ollama_client.chat.completions.create(
                    model=Config.OLLAMA_MODEL,
                    messages=[
                        {"role": "system", "content": "You are a precise medical data extractor. Output JSON only."},
                        {"role": "user", "content": prompt + f"\n\nREPORT IMAGE CONTENT (OCR TEXT):\n{page_content}"}
                    ],
                    temperature=0.0, # Strict for data extraction
                    max_tokens=4000
                )
                
                # Parse JSON
                content = response.choices[0].message.content.strip()
                # Clean code blocks if present
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                try:
                    data = json.loads(content)
                    print(f"    ✅ Parsed JSON for Page {page_idx}")
                    
                    # Merge Patient Info (Prefer fuller info)
                    new_p_info = data.get('patient_info', {})
                    if new_p_info:
                        curr_p = aggregated_results['patient_info']
                        for k, v in new_p_info.items():
                             # If new value is valid and (current is missing or empty)
                             if v and str(v).lower() not in ["", "null", "none", "n/a"]:
                                 if k not in curr_p or not curr_p[k]:
                                     curr_p[k] = v
                                     
                    # Merge Medical Tests
                    new_tests = data.get('medical_tests', [])
                    if new_tests:
                        print(f"    found {len(new_tests)} tests")
                        aggregated_results['medical_tests'].extend(new_tests)
                        
                except json.JSONDecodeError as je:
                    print(f"    ⚠️ Error parsing JSON for page {page_idx}: {je}")
                    print(f"    Raw content preview: {content[:100]}...")
                    continue

            # --- STEP 3: SAVE TO DATABASE ---
            print("💾 Saving to Database...")
            saved_report_id = None
            try:
                user_id = get_jwt_identity()
                if user_id:
                     # Get profile_id if provided (for family profiles)
                     profile_id = request.form.get('profile_id')
                     if profile_id and str(profile_id).lower() in ['null', 'undefined', '']:
                         profile_id = None
                         
                     # Create Report
                     p_info = aggregated_results['patient_info']
                     
                     # Parser helper for date
                     r_date = datetime.now()
                     if p_info.get('report_date'):
                         try:
                             # Try parsing various formats if needed, but Prompt requests YYYY-MM-DD
                             r_date = datetime.strptime(p_info['report_date'], "%Y-%m-%d")
                         except:
                             print(f"    ⚠️ Could not parse date: {p_info.get('report_date')}, using Now.")
                             pass
                     
                     # Combine text for hash
                     full_text = "\n".join([page[1] for page in extracted_text_pages])
                     report_hash = hashlib.sha256(full_text.encode('utf-8')).hexdigest()
                     
                     # Get filename
                     original_filename = files[0].filename if files else "uploaded_file"
                     
                     # Extract doctor names
                     doctor_names = p_info.get('doctor_name')
                     if doctor_names:
                         # Use validator to clean up doctor names
                         doctor_names = MedicalValidator.extract_doctor_names(doctor_names)

                     new_report = Report(
                        user_id=user_id,
                        profile_id=profile_id, # Added profile_id
                        patient_name=p_info.get('name'),
                        patient_age=p_info.get('age'),
                        patient_gender=p_info.get('gender'),
                        doctor_names=doctor_names,
                        report_date=r_date,
                        report_type="General Medical Report",
                        report_hash=report_hash,
                        original_filename=original_filename,
                        report_name=original_filename,
                        created_at=datetime.now(timezone.utc)
                     )
                     db.session.add(new_report)
                     db.session.flush()
                     
                     # Add Fields with Validation
                     consolidated_data = [] 
                     
                     for test in aggregated_results['medical_tests']:
                         # Map prompt keys to DB keys
                         raw_item = {
                             "field_name": test.get('test_name'),
                             "field_value": str(test.get('result_value')),
                             "field_unit": test.get('unit'),
                             "normal_range": test.get('normal_range'),
                             "is_normal": None,
                             "flag": test.get('flag')
                         }
                         
                         # VALIDATE AND CALCULATE IS_NORMAL
                         # Use MedicalValidator to normalize and check ranges
                         validated_item = MedicalValidator.validate_and_normalize_field(
                             raw_item, 
                             patient_gender=p_info.get('gender')
                         )
                         
                         consolidated_data.append(validated_item)
                         
                         field = ReportField(
                             report_id=new_report.id,
                             user_id=user_id,
                             field_name=validated_item['field_name'],
                             field_value=validated_item['field_value'],
                             field_unit=validated_item['field_unit'],
                             normal_range=validated_item['normal_range'],
                             is_normal=validated_item['is_normal']
                         )
                         db.session.add(field)
                     
                     db.session.commit()
                     saved_report_id = new_report.id
                     print(f"✅ Saved Report ID: {saved_report_id}")
            except Exception as e:
                db.session.rollback()
                print(f"⚠️ DB Save Error: {e}")
                raise e

            # RESTORE OLD DATA STRUCTURE
            final_response = {
                "personal_info": {
                    "patient_name": aggregated_results['patient_info'].get('name'),
                    "patient_age": aggregated_results['patient_info'].get('age'),
                    "patient_gender": aggregated_results['patient_info'].get('gender'),
                    "patient_dob": None, 
                    "report_date": aggregated_results['patient_info'].get('report_date'),
                    "doctor_names": aggregated_results['patient_info'].get('doctor_name')
                },
                "medical_data": consolidated_data, # Now contains validated data with is_normal
                "medical_info": consolidated_data, 
                "profile_id": request.form.get('profile_id'), # Echo back profile_id
                "report_id": saved_report_id,
                "debug_metadata": {
                    "total_pages_processed": total_pages,
                    "model_used": Config.OLLAMA_MODEL
                }
            }

            return final_response, 200

        except Exception as e:
            print(f"❌ Server Error: {e}")
            return {"error": str(e)}, 500
