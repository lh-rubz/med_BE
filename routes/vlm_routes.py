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


def recalculate_normality(medical_data):
    """
    Programmatically recalculate is_normal based on value and range.
    Handles complex ranges and missing values.
    """
    if not medical_data:
        return medical_data

    for item in medical_data:
        try:
            val_str = str(item.get('field_value', '')).strip()
            range_str = str(item.get('normal_range', '')).strip()

            # Skip empty
            if not val_str or not range_str or val_str.lower() in ['n/a', 'nan', ''] or range_str in ['-', '']:
                item['is_normal'] = None
                continue

            # Parse Value
            val_clean = re.sub(r'[^\\d\.\-]', '', val_str)
            if not val_clean:
                continue

            val = float(val_clean)

            # Parse Range
            min_val = float('-inf')
            max_val = float('inf')

            range_match = re.search(r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)', range_str)
            if range_match:
                min_val = float(range_match.group(1))
                max_val = float(range_match.group(2))
            elif '<' in range_str:
                num_match = re.search(r'(\d+(?:\.\d+)?)', range_str)
                if num_match:
                    max_val = float(num_match.group(1))
            elif '>' in range_str:
                num_match = re.search(r'(\d+(?:\.\d+)?)', range_str)
                if num_match:
                    min_val = float(num_match.group(1))

            # Check Normality
            if min_val != float('-inf') or max_val != float('inf'):
                is_norm = (min_val <= val <= max_val)
                item['is_normal'] = is_norm

        except Exception as e:
            item['is_normal'] = None

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


def calculate_is_normal(field_value, normal_range, field_type='measurement', patient_gender=None):
    """
    Calculate if a field value is within normal range.
    Handles gender-specific, age-specific, categorical, and simple ranges.
    Extracts gender from patient_gender parameter (e.g., "Female/20 Years" or "Female").
    """
    try:
        field_value_str = str(field_value).strip() if field_value else ''
        normal_range_str = str(normal_range).strip() if normal_range else ''
        
        if not normal_range_str or not field_value_str:
            return False
        
        # Extract numeric value
        numeric_value = None
        try:
            import re
            num_match = re.search(r'-?\d+\.?\d*', field_value_str)
            if num_match:
                numeric_value = float(num_match.group())
        except (ValueError, AttributeError):
            pass
        
        # Handle qualitative results
        if numeric_value is None:
            field_lower = field_value_str.lower()
            abnormal_keywords = ['high', 'low', 'abnormal', 'positive', 'toxicity', 'deficient', 'insufficient']
            return not any(kw in field_lower for kw in abnormal_keywords)
        
        import re
        normal_range_lower = normal_range_str.lower()
        
        # Extract patient gender
        extracted_gender = None
        if patient_gender:
            gender_str = str(patient_gender).lower()
            if 'female' in gender_str or 'f' in gender_str or 'woman' in gender_str:
                extracted_gender = 'female'
            elif 'male' in gender_str or 'm' in gender_str or 'man' in gender_str:
                extracted_gender = 'male'
        
        # ===== TRY GENDER-SPECIFIC RANGES FIRST =====
        # Patterns: "Male: 4.5-5.9, Female: 4.1-5.1" or "Men: Up to 40, Women: Up to 32"
        if extracted_gender:
            gender_patterns = [
                (r'female\s*:\s*([^,]+?)(?=,|$)', 'female'),
                (r'women\s*:\s*([^,]+?)(?=,|$)', 'female'),
                (r'male\s*:\s*([^,]+?)(?=,|$)', 'male'),
                (r'men\s*:\s*([^,]+?)(?=,|$)', 'male'),
                (r'adult\s+female\s*:\s*([^,]+?)(?=,|$)', 'female'),
                (r'adult\s+male\s*:\s*([^,]+?)(?=,|$)', 'male'),
            ]
            
            for pattern, gender_type in gender_patterns:
                if gender_type == extracted_gender:
                    match = re.search(pattern, normal_range_lower)
                    if match:
                        gender_range = match.group(1).strip()
                        if _check_range_value(numeric_value, gender_range):
                            return True
        
        # ===== TRY CATEGORICAL RANGES =====
        # Patterns: "Deficient: <10, Insufficient: 11-30, Sufficient: 31-100, Toxicity: >100"
        category_pattern = r'([a-z\s]+?)\s*:\s*([^,]+?)(?=(?:,\s*[a-z]|$))'
        category_matches = list(re.finditer(category_pattern, normal_range_lower))
        
        if category_matches:
            for match in category_matches:
                category_name = match.group(1).strip()
                range_text = match.group(2).strip()
                
                if _check_range_value(numeric_value, range_text):
                    # Value is in this category - check if category is normal
                    abnormal_cats = ['deficient', 'insufficient', 'high', 'low', 'abnormal', 'toxic', 'toxicity', 'positive', 'elevated']
                    return not any(abn in category_name for abn in abnormal_cats)
        
        # ===== TRY SIMPLE RANGES =====
        # Handle "Up to", "Below", "Above"
        if 'up to' in normal_range_lower:
            match = re.search(r'up to\s+(\d+\.?\d*)', normal_range_lower)
            if match:
                return numeric_value <= float(match.group(1))
        
        if 'below' in normal_range_lower:
            match = re.search(r'below\s+(\d+\.?\d*)', normal_range_lower)
            if match:
                return numeric_value < float(match.group(1))
        
        if 'above' in normal_range_lower or 'greater than' in normal_range_lower:
            match = re.search(r'(?:above|greater than)\s+(\d+\.?\d*)', normal_range_lower)
            if match:
                return numeric_value > float(match.group(1))
        
        # Handle comparison operators
        if normal_range_lower.startswith('<') and not normal_range_lower.startswith('<='):
            match = re.search(r'<\s*(\d+\.?\d*)', normal_range_lower)
            if match:
                return numeric_value < float(match.group(1))
        
        if normal_range_lower.startswith('>') and not normal_range_lower.startswith('>='):
            match = re.search(r'>\s*(\d+\.?\d*)', normal_range_lower)
            if match:
                return numeric_value > float(match.group(1))
        
        if '<=' in normal_range_lower:
            match = re.search(r'<=\s*(\d+\.?\d*)', normal_range_lower)
            if match:
                return numeric_value <= float(match.group(1))
        
        if '>=' in normal_range_lower:
            match = re.search(r'>=\s*(\d+\.?\d*)', normal_range_lower)
            if match:
                return numeric_value >= float(match.group(1))
        
        # Handle "min - max" ranges
        matches = re.findall(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)', normal_range_str)
        if matches:
            for min_str, max_str in matches:
                min_val = float(min_str)
                max_val = float(max_str)
                if min_val <= numeric_value <= max_val:
                    return True
        
        return False
        
    except Exception as e:
        print(f"Error calculating is_normal: {e}")
        return False


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
    
    # Comparison operators
    if range_text.startswith('<') and not range_text.startswith('<='):
        match = re.search(r'<\s*(\d+\.?\d*)', range_text)
        if match:
            return numeric_value < float(match.group(1))
    
    if range_text.startswith('>') and not range_text.startswith('>='):
        match = re.search(r'>\s*(\d+\.?\d*)', range_text)
        if match:
            return numeric_value > float(match.group(1))
    
    if range_text.startswith('<='):
        match = re.search(r'<=\s*(\d+\.?\d*)', range_text)
        if match:
            return numeric_value <= float(match.group(1))
    
    if range_text.startswith('>='):
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
                print(f"📄 OCR Text Preview:\n{ocr_text[:300]}...\n")
            except Exception as e:
                print(f"⚠️  OCR failed: {e}, using image-only mode")
            
            # Step 2: VLM
            print(f"🤖 Step 2: Structuring data with VLM (hybrid mode)...")
            yield f"data: {json.dumps({'percent': current_progress + 10, 'message': f'Understanding medical values on page {idx}...'})}\n\n"
            
            # Build prompt (Reusing logic)
            # Build OPTIMIZED extraction prompt (reduced by ~40%)
            prompt_text = f"""Extract ALL medical data from this image (page {idx}/{total_pages}).

CRITICAL RULES:
1. Extract EVERY test with its EXACT value, unit, and normal range as shown.
2. Report Identification:
   - report_name: Extract the EXACT title written on the report (e.g., "Detailed Hemogram", "Lipid Profile", "HAEMATOLOGY REPORT").
   - report_type: Choose the CLOSEST match from: {', '.join(REPORT_TYPES)}. Default to "Other" if no match.
3. CRITICAL - Extract CORRECT doctor names:
   - Look for "Ref. By:", "Ref By:", "Referred By:", "Referring Doctor:", "Doctor Name:", or "Dr." 
   - Extract FULL name without title (e.g., "Dr. Hiren Shah" → "Hiren Shah")
   - LEAVE EMPTY if NO doctor name visible on report
4. Preserve EXACT decimal precision (e.g., "14.5" not "14.50" or "15")
5. For qualitative results ("Normal", "NAD", "Negative"), put in field_value
6. CRITICAL - Extract report_date as YYYY-MM-DD:
   - Look for "Report Date:", "Date:", "Sample Date:" fields
   - Extract the EXACT date shown on the report (NOT today's date)
   - Format as YYYY-MM-DD (e.g., "01-02-2024" → "2024-02-01")
7. Extract patient details:
   - patient_age: Extract age if found (e.g., "20 Years", "45 Y", "45"). If not found, use empty string.
   - patient_gender: Extract from "Gender & Age:" or similar field (e.g., "Female/20 Years" → "Female").
8. CRITICAL - Extract normal_range EXACTLY as shown in the "Normal Ranges" column:
   - PRESERVE the COMPLETE text exactly, character by character
   - DO NOT simplify, parse, or modify the range
   - Examples to preserve exactly:
     * "12 - 16 g/dL" → Extract as: "12 - 16 g/dL"
     * "Male: 4.5 - 5.9, Female: 4.1 - 5.1" → Extract as: "Male: 4.5 - 5.9, Female: 4.1 - 5.1"
     * "Deficient: <10, Insufficient: 11-30, Sufficient: 31-100, Toxicity: >100" → Extract exact text
     * "Normal: <6 mg/dL" → Extract as: "Normal: <6 mg/dL"
     * "Normal: 187 - 883, Sufficiency: >350" → Extract exact text
   - Only remove units if they repeat in every part (rare cases)
   - EACH TEST HAS ITS OWN UNIQUE NORMAL RANGE - DO NOT COPY RANGES BETWEEN TESTS
9. If value marked "High", "Low", "Marked Low", etc., add to notes
10. Extract category/section for EACH test:
    - Look for section headers: "HAEMATOLOGY REPORT", "BIOCHEMISTRY", "DIFFERENTIAL COUNT", "ELECTROLYTES", "ENDOCRINOLOGY REPORT", "SEROLOGY REPORT", etc.
    - Use the exact section name found
    - If no section visible, use empty string

Return ONLY valid JSON (no markdown, no code blocks):
{{
    "patient_name": "...",
    "patient_age": "...",
    "patient_gender": "...",
    "report_date": "2024-02-01",
    "report_name": "HAEMATOLOGY REPORT",
    "report_type": "...",
    "doctor_names": "",
    "total_fields_in_image": <count>,
    "medical_data": [
        {{
            "field_name": "Haemoglobin",
            "field_value": "14.5",
            "field_unit": "g/dL",
            "normal_range": "12 - 16 g/dL",
            "is_normal": true,
            "field_type": "measurement",
            "category": "HAEMATOLOGY REPORT",
            "notes": ""
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

        # Step 4: Duplicate Check (using report hash)
        yield f"data: {json.dumps({'percent': 85, 'message': 'Ensuring this is a new report...'})}\n\n"
        
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
             print(f"Duplicate Check Error: {e}")

        # Step 5: Saving
        yield f"data: {json.dumps({'percent': 90, 'message': 'Saving your report...'})}\n\n"
        print(f"💾 Saving report to database...")
        
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

            new_report = Report(
                user_id=current_user_id,
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
                        is_normal_value = calculated_is_normal if normal_range else bool(vlm_is_normal)
                    
                    field = ReportField(
                        report_id=new_report.id,
                        user_id=current_user_id,
                        field_name=item.get('field_name', 'Unknown'),
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
