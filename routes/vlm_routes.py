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


# Initialize EasyOCR reader globally to avoid reloading model on every request
# Added 'ar' for Arabic support
reader = easyocr.Reader(['en', 'ar'])

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

def verify_and_correct_with_llm(extracted_data, raw_text):
    """
    Uses LLM to verify and correct the extracted data against the raw text.
    This acts as a self-correction mechanism.
    """
    try:
        prompt = f"""You are a meticulous medical data verification assistant.
Your goal is to ensure the extracted JSON data is 100% accurate matches the Raw Text.

RAW TEXT FROM REPORT:
---
{raw_text}
---

CURRENT EXTRACTED DATA (May have errors):
---
{json.dumps(extracted_data, indent=2, ensure_ascii=False)}
---

TASK:
1. Compare every field in the "CURRENT EXTRACTED DATA" against the "RAW TEXT".
2. Fix any MISALIGNED values. Example: If "Lymphocytes" is 2.9 in data but text shows "Lymphocytes 257", CHANGE IT TO 257.
3. Fix any NAME swaps. Ensure Doctor Name is correct and Patient Name is correct.
4. GENDER NORMALIZATION: You MUST convert Arabic gender to English:
   - "أنثى", "انثى", "Female" -> "Female"
   - "ذكر", "Male" -> "Male"
   - Return ONLY "Male" or "Female".
5. If a value is missing in data but present in text, ADD IT.
6. If a value is present in data but NOT in text (hallucinated), REMOVE IT.
7. Return the FULLY CORRECTED JSON object.

OUTPUT FORMAT:
Return ONLY the raw JSON object. No markdown formatting, no explanations.
"""

        print("Refining data with LLM self-correction...")
        response = ollama_client.chat.completions.create(
            model=Config.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise medical data extraction assistant. Output only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1, # Low temperature for precision
            max_tokens=4000
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean potential markdown code blocks if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        corrected_data = json.loads(content)
        
        # Force gender normalization on the LLM output
        if 'personal_info' in corrected_data and 'patient_gender' in corrected_data['personal_info']:
            corrected_data['personal_info']['patient_gender'] = normalize_gender(corrected_data['personal_info']['patient_gender'])

        print("LLM self-correction complete.")
        return corrected_data

    except Exception as e:
        print(f"LLM correction failed: {e}")
        # Fallback to original data if LLM fails
        return extracted_data


@vlm_ns.route('/chat')
class ChatResource(Resource):
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
            print(f"Processing file: {uploaded_file.filename}")

            if uploaded_file.filename.lower().endswith('.pdf'):
                # Process multi-page PDF files
                # Use stream=uploaded_file.read() to load the file into memory for PyMuPDF
                file_content = uploaded_file.read()
                pdf_document = fitz.open(stream=file_content, filetype="pdf")
                
                print(f"PDF has {len(pdf_document)} pages")
                
                for page_num in range(len(pdf_document)):
                    page = pdf_document[page_num]
                    
                    # Try direct text extraction first (faster and more accurate for native PDFs)
                    text = page.get_text()
                    
                    # Check for Arabic characters in the extracted text
                    # PyMuPDF often has issues with Arabic text direction/ordering, so we prefer OCR for Arabic
                    has_arabic = bool(re.search(r'[\u0600-\u06FF]', text))
                    
                    # If direct extraction yields little text, or contains Arabic (safer to use OCR), fall back to OCR
                    if len(text.strip()) < 100 or has_arabic:
                        reason = "contains Arabic" if has_arabic else "minimal text found"
                        print(f"Page {page_num + 1}: {reason}, using OCR...")
                        
                        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0)) # 2x zoom for better OCR
                        img_data = pix.tobytes("png")
                        # Use paragraph=True to group text into lines/blocks, preserving table row structure better
                        result = reader.readtext(img_data, detail=0, paragraph=True)
                        page_text = "\n".join(result)
                        extracted_text += f"\n--- Page {page_num + 1} ---\n{page_text}\n"
                print(f"Page {page_num + 1} processed. Text length: {len(page_text)}")
                    else:
                        print(f"Page {page_num + 1}: extracted {len(text)} characters using native text extraction")
                        extracted_text += f"\n--- Page {page_num + 1} ---\n{text}\n"
                    print(f"Page {page_num + 1} processed (Native). Text length: {len(text)}")
                        
            elif uploaded_file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                # Process image files using easyocr
                print("Processing image file with OCR...")
                # Use paragraph=True here as well
                result = reader.readtext(uploaded_file.read(), detail=0, paragraph=True)
                extracted_text = "\n".join(result)
            else:
                return {"error": "Unsupported file type. Please upload a PDF or image."}, 400

            print(f"Total extracted text length: {len(extracted_text)}")
            
            # Extract personal and medical information (Initial Pass)
            personal_info = extract_personal_info(extracted_text)
            medical_info = extract_medical_data(extracted_text)

            # Ensure fields are clean and consistent
            cleaned_medical_info = {
                field: details
                for field, details in medical_info.items()
                if details.get("value") or details.get("normal_range")
            }
            
            initial_data = {
                "personal_info": personal_info,
                "medical_info": cleaned_medical_info
            }

            # Self-Correction Pass: Use LLM to verify and fix the data
            final_data = verify_and_correct_with_llm(initial_data, extracted_text)

            return final_data, 200

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": f"Failed to process file: {str(e)}"}, 500
