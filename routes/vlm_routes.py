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
from utils.ocr_extractor import get_ocr_instance
from utils.vlm_prompts import get_main_vlm_prompt, get_table_retry_prompt, get_personal_info_prompt
from utils.vlm_correction import analyze_extraction_issues, generate_corrective_prompt, generate_prompt_enhancement_request
from utils.vlm_self_extraction_prompt import get_self_prompting_analysis_prompt, get_self_directed_extraction_prompt, get_simplified_extraction_prompt
from utils.vlm_line_by_line_verifier import verify_extracted_fields_against_image_openai
from utils.vlm_strict_table_extraction import get_strict_table_extraction_prompt, get_alignment_verification_prompt
from utils.medical_data_postprocessor import MedicalDataPostProcessor
from ollama import Client
from utils.extract_personal_info import extract_personal_info, extract_medical_data
from utils.llm_text_organizer import get_text_organizer_prompt, get_enhanced_extraction_prompt, parse_organized_text

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
            unique_map[key] = item.copy()
        else:
            # Merge information
            existing = unique_map[key]
            
            # If current has value and existing doesn't, take it
            if not existing.get('field_value') or existing.get('field_value') in ["", "N/A", "n/a"]:
                if item.get('field_value') and item.get('field_value') not in ["", "N/A", "n/a"]:
                    existing['field_value'] = item.get('field_value')
            
            # If current has range and existing doesn't, take it
            if not existing.get('normal_range') or existing.get('normal_range') in ["", "-", "N/A"]:
                if item.get('normal_range') and item.get('normal_range') not in ["", "-", "N/A"]:
                    existing['normal_range'] = item.get('normal_range')
            
            # Same for unit
            if not existing.get('field_unit') or len(str(existing.get('field_unit'))) < 2:
                if item.get('field_unit') and len(str(item.get('field_unit'))) >= 2:
                    existing['field_unit'] = item.get('field_unit')

            # Append notes if different
            note = item.get('notes', '').strip()
            if note and note not in existing.get('notes', ''):
                existing['notes'] = (existing.get('notes', '') + "; " + note).strip("; ")
            
    return list(unique_map.values())


def recalculate_normality(medical_data, patient_gender=None):
    """
    Programmatically recalculate is_normal based on value and range using MedicalValidator.
    """
    if not medical_data:
        return medical_data

    from utils.medical_validator import MedicalValidator
    
    for item in medical_data:
        val_str = str(item.get('field_value', '')).strip()
        range_str = str(item.get('normal_range', '')).strip()
        current_is_normal = item.get('is_normal')
        
        item['is_normal'] = MedicalValidator.calculate_is_normal(
            val_str, 
            range_str, 
            current_is_normal=current_is_normal,
            patient_gender=patient_gender
        )

    return medical_data

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
reader = None  # Lazy-loaded on first use

def get_reader():
    global reader
    if reader is None:
        reader = easyocr.Reader(['en', 'ar'])
    return reader

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
    1. Group data by sections (e.g., Haematology Report, Biochemistry).
    2. Extract all medical fields with their values, units, and normal ranges.
    3. Extract doctor names and ensure they are complete.
    4. For each field, calculate and set "is_normal" based on the value and range.
    5. Ensure all extracted data is accurate and matches the page content.
    6. Handle both Arabic and English text correctly.

    OUTPUT FORMAT:
    {
        "sections": [
            {
                "section_name": "Haematology Report",
                "fields": [
                    {
                        "field_name": "",
                        "field_value": "",
                        "field_unit": "",
                        "normal_range": "",
                        "is_normal": true/false/null,
                        "notes": ""
                    }
                ]
            }
        ],
        "doctor_names": ""
    }
    """
    return f"""
    TASK: Extract medical data from the report page.

    PAGE INDEX: {page_idx}/{total_pages}

    PAGE CONTENT:
    {page_text}

    INSTRUCTIONS:
    1. Group data by sections (e.g., Haematology Report, Biochemistry).
    2. Extract all medical fields with their values, units, and normal ranges.
    3. Extract doctor names and ensure they are complete.
    4. For each field, calculate and set "is_normal" based on the value and range.
    5. Ensure all extracted data is accurate and matches the page content.
    6. Handle both Arabic and English text correctly.

    OUTPUT FORMAT:
    {
        "sections": [
            {
                "section_name": "Haematology Report",
                "fields": [
                    {
                        "field_name": "",
                        "field_value": "",
                        "field_unit": "",
                        "normal_range": "",
                        "is_normal": true/false/null,
                        "notes": ""
                    }
                ]
            }
        ],
        "doctor_names": ""
    }
    """

def process_page_with_llm(page_text, page_idx, total_pages):
    """
    Process a single page using a two-step strategy:
    1. Generate a strict prompt for the page.
    2. Use the generated prompt to extract data.
    """
    debug_logs = []

    # Step 1: Generate Prompt
    try:
        generated_prompt = generate_prompt_for_page(page_text, page_idx, total_pages)
        print(f"Generated Prompt for Page {page_idx}/{total_pages}:\n{generated_prompt}")  # Print the prompt to console
        debug_logs.append({
            "step": "1_generate_prompt",
            "page": page_idx,
            "prompt_preview": generated_prompt[:200] + "..."
        })
    except Exception as e:
        print(f"Prompt generation failed for page {page_idx}: {e}")
        debug_logs.append({"step": "1_generate_prompt_error", "error": str(e)})
        return None, debug_logs

    # Step 2: Extract Data
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
            "step": "2_extraction",
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
        debug_logs.append({"step": "2_extraction_error", "error": str(e)})
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
       - Fix numerical values (e.g., "5.2" vs "52"). PRESERVE symbols like <, >, <= if present.
       - Fix units (e.g., "g/L" vs "g/dL"). TRANSLATE Arabic units to standard English units (e.g., "U/L").
       - Fix names (Doctor vs Patient).
       - REMOVE hallucinated fields (not in text).
       - ADD missing fields (visible in text but missing in JSON).
    3. RE-EVALUATE "is_normal":
       - Keep existing value or set to null. Our system will recalculate it mathematically.
    
    4. HEADER FIELDS:
       - Ensure "patient_name" is the ACTUAL person name (e.g., "رئيسة خضر طالب خطيب").
       - DO NOT use "شؤون اجتماعية" (Insurance) or Clinic names as patient name.
       - Ensure "patient_gender" is "Male" or "Female".

    OUTPUT:
    - Return a FULL JSON OBJECT matching the input structure:
    {{
        "patient_name": "...",
        "patient_age": "...",
        "patient_gender": "...",
        "report_date": "...",
        "doctor_names": "...",
        "medical_data": [ ... objects with field_name, field_value, field_unit, normal_range, notes ... ]
    }}
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
        # Render page to an image with 3.0x zoom (Higher quality for OCR ~216 DPI)
        pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
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
    
    # Compress to JPEG with quality 95 (Very high quality for OCR/VLM)
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=95, optimize=True)
    compressed_data = output.getvalue()
    
    original_size = len(image_data) / 1024  # KB
    compressed_size = len(compressed_data) / 1024  # KB
    reduction = ((original_size - compressed_size) / original_size * 100) if original_size > 0 else 0
    
    print(f"  📦 Compressed: {original_size:.1f}KB → {compressed_size:.1f}KB ({reduction:.1f}% reduction)")
    
    return compressed_data


def calculate_is_normal(field_value, normal_range, field_type='measurement', patient_gender=None):
    """
    Consolidated normality calculation.
    """
    from utils.medical_validator import MedicalValidator
    return MedicalValidator.calculate_is_normal(field_value, normal_range, patient_gender=patient_gender)


def _check_range_value(numeric_value, range_text):
    """Check if numeric value falls within range text"""
    import re
    range_text = str(range_text).strip().lower()
    
    # "Up to", "Below", "Above"
    if 'up to' in range_text:
        match = re.search(r'up to\s+(\d+\.?\d*)', range_text)
        if match:
            return numeric_value <= float(match.group(1))
    
    if 'below' in range_text:
        match = re.search(r'below\s+(\d+\.?\d*)', range_text)
        if match:
            return numeric_value < float(match.group(1))
    
    if 'less than' in range_text:
        match = re.search(r'less than\s+(\d+\.?\d*)', range_text)
        if match:
            return numeric_value < float(match.group(1))
    
    if 'more than' in range_text or 'greater than' in range_text:
        match = re.search(r'(?:more than|greater than)\s+(\d+\.?\d*)', range_text)
        if match:
            return numeric_value > float(match.group(1))
    
    if 'above' in range_text:
        match = re.search(r'above\s+(\d+\.?\d*)', range_text)
        if match:
            return numeric_value > float(match.group(1))
    
    # Comparison operators
    if range_text.startswith('<') and not range_text.startswith('<='):
        match = re.search(r'<\s*(\d+\.?\d*)', range_text)
        if match:
            return numeric_value < float(match.group(1))
    
    if range_text.startswith('>') and not range_text.startswith('>='):
        match = re.search(r'>\s*(\d+\.?\d*)', range_text)
        if match:
            return numeric_value > float(match.group(1))
    
    if '<=' in range_text:
        match = re.search(r'<=\s*(\d+\.?\d*)', range_text)
        if match:
            return numeric_value <= float(match.group(1))
    
    if '>=' in range_text:
        match = re.search(r'>=\s*(\d+\.?\d*)', range_text)
        if match:
            return numeric_value >= float(match.group(1))
    
    # "min-max" range
    match = re.search(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)', range_text)
    if match:
        min_val = float(match.group(1))
        max_val = float(match.group(2))
        return min_val <= numeric_value <= max_val
    
    return False



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
            except Exception as e:
                print(f"⚠️  OCR failed: {e}, using image-only mode")
            
            # Step 1.5: LLM Text Organizer (Stage 1 of two-stage extraction)
            organized_text = None
            organized_data = None
            if ocr_text and len(ocr_text) > 100:  # Only organize if we have enough text
                print(f"🧹 Step 1.5: Organizing OCR text with LLM...")
                yield f"data: {json.dumps({'percent': current_progress + 5, 'message': f'Organizing text from page {idx}...'})}\n\n"
                
                try:
                    organizer_prompt = get_text_organizer_prompt() + ocr_text
                    
                    # Text-only LLM call (no image, faster)
                    organizer_completion = ollama_client.chat.completions.create(
                        model=Config.OLLAMA_MODEL,
                        messages=[{'role': 'user', 'content': organizer_prompt}],
                        temperature=0.1
                    )
                    organized_text = organizer_completion.choices[0].message.content.strip()
                    print(f"✅ LLM organized text ({len(organized_text)} chars)")
                    print(f"📋 Organized preview:\n{organized_text[:500]}...")
                    
                    # Parse organized text as backup
                    organized_data = parse_organized_text(organized_text)
                    if organized_data.get('medical_data'):
                        print(f"   📊 Parsed {len(organized_data['medical_data'])} test results from organized text")
                    if organized_data.get('patient_name'):
                        print(f"   👤 Found patient: {organized_data['patient_name']}")
                    if organized_data.get('medical_data'):
                        print(f"   📊 Parsed {len(organized_data['medical_data'])} medical tests from organized text")
                except Exception as org_err:
                    print(f"⚠️  Text organization failed: {org_err}, continuing with raw OCR")
            
            # STRATEGY: Use organized OCR data as PRIMARY source (better row alignment)
            # VLM is used for patient info and verification only
            
            # Initialize extracted_data
            extracted_data = {
                "patient_name": "",
                "patient_age": "",
                "patient_gender": "",
                "report_date": "",
                "report_name": "",
                "report_type": "",
                "doctor_names": "",
                "medical_data": []
            }
            
            # Step 2a: If organized_data has good medical tests, use it as PRIMARY
            if organized_data and organized_data.get('medical_data') and len(organized_data['medical_data']) >= 3:
                print(f"✅ Using organized OCR data as PRIMARY source ({len(organized_data['medical_data'])} fields)")
                extracted_data['medical_data'] = organized_data['medical_data']
                
                # Also use patient info from organized data
                for key in ['patient_name', 'patient_gender', 'patient_age', 'report_date', 'doctor_names']:
                    if organized_data.get(key):
                        extracted_data[key] = organized_data[key]
                
                extraction_method = "organized_ocr_primary"
            else:
                # Fallback: Use VLM for extraction
                print(f"🤖 Step 2: VLM extraction (organized text had < 3 fields)...")
                yield f"data: {json.dumps({'percent': current_progress + 10, 'message': f'Reading table data carefully on page {idx}...'})}\n\n"
                
                extraction_method = "vlm_primary"
            
            # Only call VLM if we're using vlm_primary method
            if extraction_method == "vlm_primary":
                try:
                    image_base64 = base64.b64encode(image_info['data']).decode('utf-8')
                    image_format = image_info['format']
                    
                    # Use strict table extraction prompt
                    prompt_text = get_strict_table_extraction_prompt(
                        idx=idx,
                        total_pages=total_pages
                    )
                    
                    content = []
                    if ocr_text:
                        enhanced_prompt = f"{prompt_text}\n\nOCR-EXTRACTED TEXT FOR REFERENCE:\n{ocr_text}"
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
                    print(f"🔍 RAW RESPONSE for Image {idx}:\n{'-'*40}\n{response_text[:500]}...\n{'-'*40}")
                    
                    # Parse VLM response
                    try:
                        import re
                        json_str = None
                        brace_count = 0
                        start_idx = -1
                        for i, char in enumerate(response_text):
                            if char == '{':
                                if brace_count == 0:
                                    start_idx = i
                                brace_count += 1
                            elif char == '}':
                                brace_count -= 1
                                if brace_count == 0 and start_idx != -1:
                                    json_str = response_text[start_idx:i+1]
                                    break
                        
                        if json_str:
                            vlm_data = json.loads(json_str)
                            for key in extracted_data:
                                if key in vlm_data:
                                    extracted_data[key] = vlm_data[key]
                            print(f"✅ VLM JSON extracted for Image {idx}")
                            print(f"   Medical data entries: {len(extracted_data.get('medical_data', []))}")
                    except json.JSONDecodeError as je:
                        print(f"⚠️  VLM JSON parsing failed: {je}")
                
                except Exception as vlm_err:
                    print(f"⚠️  VLM extraction failed: {vlm_err}")
            
            # Step 3: Always try VLM for patient info (it reads headers better than OCR)
            # Check what patient fields are missing
            missing_fields = []
            for field in ['patient_name', 'patient_gender', 'patient_age', 'report_date', 'doctor_names']:
                if not extracted_data.get(field):
                    missing_fields.append(field)
            
            if missing_fields:
                print(f"   🔍 Using VLM to extract patient info (missing: {', '.join(missing_fields)})...")
                try:
                    image_base64 = base64.b64encode(image_info['data']).decode('utf-8')
                    image_format = image_info['format']
                    
                    patient_prompt = """Extract patient and report information from this medical lab report image.

LOOK FOR THESE FIELDS (check header area, top of page):

1. PATIENT NAME (اسم المريض):
   - Look at the RIGHT header table.
   - Find the label "اسم المريض" and extract the text directly next to it.
   - DO NOT confuse with "التأمين" (Insurance) or "جهة الطلب" (Clinic).
   - Expected name: "رئيسة خضر طالب خطيب" or similar.

2. GENDER (الجنس):
   - Look at the RIGHT header table.
   - Find "الجنس" and extract "ذكر" (Male) or "أنثى" (Female).

3. AGE / DOB (تاريخ الميلاد):
   - Look at the RIGHT header table.
   - Find "تاريخ الميلاد" and extract the date (e.g., 01/05/1975).
   - If you see "تاريخ الطلب", that is the REPORT DATE, not birth date.

4. REPORT DATE (تاريخ الطلب):
   - Look at the LEFT header table.
   - Find "تاريخ الطلب" and extract the date/time (e.g., 2025-12-31).

5. DOCTOR NAME (الطبيب):
   - Look at the LEFT header table.
   - Find "الطبيب" and extract the name (e.g., "جهاد العملة").
   - DO NOT confuse with "جهة الطلب" (Requesting Entity/Clinic).

Return JSON only:
{
    "patient_name": "exact name as shown",
    "patient_age": "number only (e.g., 35)",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD format",
    "doctor_names": "doctor name if found"
}

RULES:
- Return empty string "" if not found (don't guess)
- Use exact spelling from image
- Convert date to YYYY-MM-DD format"""
                    
                    content = [
                        {'type': 'text', 'text': patient_prompt},
                        {'type': 'image_url', 'image_url': {'url': f'data:image/{image_format};base64,{image_base64}'}}
                    ]
                    
                    completion = ollama_client.chat.completions.create(
                        model=Config.OLLAMA_MODEL,
                        messages=[{'role': 'user', 'content': content}],
                        temperature=0.1
                    )
                    patient_response = completion.choices[0].message.content.strip()
                    
                    # Parse patient info
                    import re
                    json_match = re.search(r'\{.*\}', patient_response, re.DOTALL)
                    if json_match:
                        patient_data = json.loads(json_match.group())
                        for key in ['patient_name', 'patient_age', 'patient_gender', 'report_date', 'doctor_names']:
                            if patient_data.get(key) and not extracted_data.get(key):
                                extracted_data[key] = patient_data[key]
                        print(f"   👤 Patient info enriched from VLM")
                except Exception as pe:
                    print(f"   ⚠️  Patient info extraction failed: {pe}")
            
            # Continue with validation and processing
            print(f"📊 Final extraction method: {extraction_method}")
            print(f"   Fields extracted: {len(extracted_data.get('medical_data', []))}")
            
            # Run verification on extracted data
            if extracted_data.get('medical_data') and len(extracted_data['medical_data']) > 0:
                try:
                    image_base64 = base64.b64encode(image_info['data']).decode('utf-8')
                    image_format = image_info['format']
                    
                    print(f"🔎 Running verification for page {idx}...")
                    verified_fields, verification_report = verify_extracted_fields_against_image_openai(
                        extracted_data['medical_data'],
                        image_base64,
                        image_format,
                        ollama_client,
                        Config.OLLAMA_MODEL,
                        page_num=idx,
                        total_pages=total_pages,
                        run_detailed_check=False  # Disable detailed field-by-field checks
                    )
                    extracted_data['medical_data'] = verified_fields
                    print(f"✅ Verification status: {verification_report.get('verification_status', 'UNKNOWN')}")
                except Exception as ver_err:
                    print(f"⚠️  Verification failed: {ver_err}")
                
                field_count = len(extracted_data['medical_data'])
                all_extracted_data.extend(extracted_data['medical_data'])
                print(f"✅ Extracted {field_count} field(s) from page {idx}")
            else:
                print(f"⚠️  No medical_data found for page {idx}")
            
            # Capture patient info from first good page
            if not patient_info or not patient_info.get('patient_name'):
                if extracted_data.get('patient_name'):
                    patient_info = extracted_data
                elif organized_data and organized_data.get('patient_name'):
                    print(f"   👤 Using patient info from organized text: {organized_data.get('patient_name')}")
                    patient_info = organized_data
                elif extracted_data.get('medical_data'):
                    patient_info = extracted_data
            
            # Enrich patient_info with organized_data if available
            if organized_data:
                for key in ['patient_name', 'patient_gender', 'patient_age', 'report_date', 'doctor_names']:
                    if organized_data.get(key) and not patient_info.get(key):
                        patient_info[key] = organized_data[key]
                        print(f"   ✨ Enriched {key} from organized text: {organized_data[key]}")
            
            print(f"✅ Page {idx} Analysis Complete. Found {len(extracted_data.get('medical_data', []))} data points.")

        # Step 4: Post-Processing & Validation
        yield f"data: {json.dumps({'percent': 75, 'message': 'Cleaning and validating results...'})}\n\n"
        print(f"🧹 Cleaning {len(all_extracted_data)} extracted items...")
        
        # Combine raw data
        raw_data = {
            'patient_name': patient_info.get('patient_name', ''),
            'patient_age': patient_info.get('patient_age', ''),
            'patient_gender': patient_info.get('patient_gender', ''),
            'report_date': patient_info.get('report_date', ''),
            'report_name': patient_info.get('report_name', 'Medical Report'),
            'report_type': patient_info.get('report_type', 'General'),
            'doctor_names': patient_info.get('doctor_names', ''),
            'medical_data': all_extracted_data
        }
        
        # Clean data: remove empty fields, validate entries
        print(f"   - Removing incomplete entries, validating structure...")
        final_data = MedicalDataPostProcessor.clean_extracted_data(
            raw_data,
            strict_validation=True
        )
        
        # Calculate is_normal for all entries
        final_data['medical_data'] = MedicalDataPostProcessor.add_is_normal_to_entries(
            final_data['medical_data'],
            patient_gender=final_data['patient_gender']
        )
        
        # Validate extraction quality
        quality_report = MedicalDataPostProcessor.validate_extraction_quality(final_data)
        print(f"   ✅ Quality Report:")
        print(f"      - Total fields: {quality_report['total_fields_extracted']}")
        print(f"      - Has patient name: {quality_report['has_patient_name']}")
        print(f"      - Has report date: {quality_report['has_report_date']}")
        if quality_report['issues']:
            print(f"      - Issues: {', '.join(quality_report['issues'])}")
        if quality_report['warnings']:
            print(f"      - Warnings: {', '.join(quality_report['warnings'])}")
        
        # Step 5: Synonym Learning & Field Standardization
        yield f"data: {json.dumps({'percent': 80, 'message': 'Learning field name variations...'})}\n\n"
        print("🧠 Learning and standardizing field names...")
        
        try:
            medical_data_list = final_data.get('medical_data', [])
            unknown_terms = []
            learned_synonyms = {}  # Maps lowercase variations to standard names
            
            # Step 1: Identify unknown terms AND build learned synonyms from DB
            for item in medical_data_list:
                original_name = item.get('field_name', '').strip()
                if not original_name or len(original_name) < 2:
                    continue
                
                # Check if we know this field already
                synonym_record = MedicalSynonym.query.filter_by(synonym=original_name.lower()).first()
                if synonym_record:
                    # Known field - add to learned_synonyms mapping
                    learned_synonyms[original_name.lower()] = synonym_record.standard_name
                    print(f"   ✓ Known: '{original_name}' → '{synonym_record.standard_name}'")
                elif original_name not in unknown_terms:
                    # Unknown field - queue for learning
                    unknown_terms.append(original_name)
            
            # Step 2: Batch learn ALL unknown terms at once
            if unknown_terms:
                print(f"   - Learning {len(unknown_terms)} new field name variations (batch)...")
                try:
                    # Create comprehensive learning prompt
                    terms_json = json.dumps(unknown_terms)
                    learning_prompt = f"""You are a medical data standardizer for multilingual medical reports.
For each test name below, identify its STANDARD medical name.
These are actual field names from medical reports (English, Arabic, or mixed).

Input: {terms_json}

For each term, do this:
1. Identify the language: Is it English, Arabic, or a mix?
2. Determine the medical test it represents
3. Find the STANDARD name (prefer the most commonly used format)
4. Handle variations intelligently:
   - Different spellings: "Hemoglobin" vs "Haemoglobin" → pick one standard
   - Abbreviations: "WBC", "CBC", "RBC" → keep standard abbreviations
   - Translations: Keep in the original language extracted from report
   - Arabic names: كرات الدم البيضاء (White Blood Cells) → either keep Arabic or translate
   - Language mix: If field is in one language, standardize within that language

STANDARDIZATION RULES:
- English medical tests: Use British English where applicable (Haemoglobin not Hemoglobin)
- Abbreviations: Keep standard medical abbreviations (WBC, RBC, HDL, LDL, ALT, AST)
- Arabic tests: Keep in Arabic if that's what was in the report, don't translate
- Parenthetical notes: Standardize "(Fasting)" consistently
- Units and ranges: These are separate fields, focus on test NAME only

Examples:
- "Hemoglobin" and "Haemoglobin" both → "Haemoglobin"
- "WBC" and "White Blood Cell Count" → "WBC" (keep abbreviation if report uses it)
- "Glucose (Fasting)" and "Fasting Glucose" → "Glucose (Fasting)"
- "Hgb" and "HGB" and "Hemoglobin" → "Haemoglobin"
- "Blood Sugar" and "Glucose" → "Glucose"
- "كرات الدم البيضاء" (Arabic WBC) → keep as "كرات الدم البيضاء" (preserve Arabic)
- "الهيموجلوبين" and "Haemoglobin" → If original is Arabic, keep Arabic; if English, use "Haemoglobin"
- "ALT" and "SGPT" and "Alanine Aminotransferase" → "Alanine aminotransferase (ALT)"

Return ONLY valid JSON (no markdown):
{{"term": "standard_name", "term2": "standard_name2"}}

Be aggressive but intelligent - group all variations of same test together."""
                    
                    response = ollama_client.chat.completions.create(
                        model=Config.OLLAMA_MODEL,
                        messages=[{'role': 'user', 'content': learning_prompt}]
                    )
                    
                    response_text = response.choices[0].message.content.strip()
                    # Clean markdown if present
                    for marker in ['```json', '```']:
                        if marker in response_text:
                            response_text = response_text.split(marker)[1].split('```')[0].strip()
                    
                    learned_map = json.loads(response_text)
                    
                    # Step 3: Save ALL learned synonyms to database
                    for original, standard in learned_map.items():
                        original = str(original).strip()
                        standard = str(standard).strip()
                        
                        if standard and standard != 'UNKNOWN' and len(standard) < 100:
                            # Save this synonym mapping
                            add_new_alias(original, standard)
                            
                            # Also ensure standard name is a self-mapping
                            standard_lower = standard.lower()
                            existing = MedicalSynonym.query.filter_by(synonym=standard_lower).first()
                            if not existing:
                                add_new_alias(standard, standard)
                            
                            # Add to our local learned_synonyms for immediate use
                            learned_synonyms[original.lower()] = standard
                            
                            if standard.lower() != original.lower():
                                print(f"   💡 Learned: '{original}' → '{standard}'")
                            else:
                                print(f"   📝 Standardized: '{standard}'")
                
                except Exception as e:
                    print(f"   ⚠️  Learning failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Step 4: Apply standardization to current report's data
            print(f"   - Standardizing {len(medical_data_list)} field names in this report...")
            final_data['medical_data'] = MedicalDataPostProcessor.standardize_field_names(
                medical_data_list,
                learned_synonyms=learned_synonyms
            )
            
            print(f"   ✅ Field name standardization complete ({len(learned_synonyms)} mappings)")
            
        except Exception as e:
            print(f"   ⚠️  Synonym learning/standardization error: {e}")
            import traceback
            traceback.print_exc()
        
        # Step 6: Duplicate Check
        yield f"data: {json.dumps({'percent': 85, 'message': 'Checking for duplicates...'})}\n\n"
        
        try:
            medical_data_list = final_data.get('medical_data', [])
            if len(medical_data_list) > 0:
                # Calculate report hash
                report_hash = hashlib.sha256(json.dumps(medical_data_list, sort_keys=True).encode()).hexdigest()
                
                # Check if this exact report already exists for this user
                existing_report = Report.query.filter_by(
                    user_id=current_user_id,
                    report_hash=report_hash
                ).first()
                
                if existing_report:
                    error_msg = f'This report appears to be a duplicate of an existing report (#{existing_report.id})'
                    yield f"data: {json.dumps({'error': error_msg, 'code': 'DUPLICATE_REPORT', 'report_id': existing_report.id})}\n\n"
                    return
        except Exception as e:
            print(f"Duplicate check error: {e}")
        
        # Step 7: Saving to Database
        yield f"data: {json.dumps({'percent': 90, 'message': 'Saving your report...'})}\n\n"
        print(f"💾 Saving {len(final_data['medical_data'])} fields to database...")
        
        new_report_id = None
        try:
            # Calculate report hash
            report_hash = hashlib.sha256(json.dumps(final_data['medical_data'], sort_keys=True).encode()).hexdigest()
            
            # Parse extracted report date (YYYY-MM-DD), fallback to now()
            report_date_obj = datetime.now(timezone.utc)
            extracted_date = final_data.get('report_date')
            if extracted_date and len(extracted_date) >= 10:
                try:
                    # Parse YYYY-MM-DD
                    report_date_obj = datetime.strptime(extracted_date[:10], '%Y-%m-%d')
                except:
                    print(f"⚠️ Could not parse report date: {extracted_date}, using now()")

            # Get user's Self profile and assign to report
            from models import Profile
            user_profile = Profile.query.filter_by(
                creator_id=current_user_id,
                relationship='Self'
            ).first()
            
            # If no 'Self' profile found, use any profile owned by user or none
            if not user_profile:
                user_profile = Profile.query.filter_by(creator_id=current_user_id).first()
            
            profile_id = user_profile.id if user_profile else None
            
            new_report = Report(
                user_id=current_user_id,
                profile_id=profile_id,
                report_date=report_date_obj,
                report_hash=report_hash,
                report_name=final_data.get('report_name'),
                report_type=final_data.get('report_type'),
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
                    field_value = item.get('field_value', '')
                    normal_range = item.get('normal_range', '')
                    field_type = item.get('field_type', 'measurement')
                    
                    # Calculate is_normal based on actual value and range
                    # First check if VLM provided a value, otherwise calculate it
                    vlm_is_normal = item.get('is_normal')
                    patient_gender = final_data.get('patient_gender', '')
                    
                    if vlm_is_normal is None or vlm_is_normal == '':
                        # VLM didn't provide is_normal, calculate it
                        calculated_is_normal = calculate_is_normal(field_value, normal_range, field_type, patient_gender)
                        is_normal_value = calculated_is_normal
                    else:
                        # Use VLM's value, but validate it by calculating
                        calculated_is_normal = calculate_is_normal(field_value, normal_range, field_type, patient_gender)
                        # Prefer the calculated value if we have a range
                        if calculated_is_normal is not None:
                            is_normal_value = calculated_is_normal
                        else:
                            # Use VLM value as fallback, but only if it's not null/empty
                            is_normal_value = bool(vlm_is_normal) if vlm_is_normal not in [None, ""] else None
                    
                    field = ReportField(
                        report_id=new_report.id,
                        user_id=current_user_id,
                        field_name=item.get('field_name', 'Unknown'),
                        standard_name=item.get('standard_name'),
                        field_value=str(field_value),
                        field_unit=str(item.get('field_unit', '')),
                        normal_range=str(normal_range),
                        is_normal=is_normal_value,
                        field_type=str(field_type),
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
