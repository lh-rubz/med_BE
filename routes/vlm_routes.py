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
    "Other"
]

def recalculate_normality(medical_data):
    """
    Programmatically recalculate is_normal based on value and range.
    Overrides LLM hallucinations.
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
            # Remove <, >, units, commas
            val_clean = re.sub(r'[^\d\.-]', '', val_str)
            if not val_clean:
                continue
            val = float(val_clean)
            
            # Parse Range
            # Handle (min-max)
            min_val = float('-inf')
            max_val = float('inf')
            
            # Standard "min-max" or "(min-max)"
            range_match = re.search(r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)', range_str)
            if range_match:
                min_val = float(range_match.group(1))
                max_val = float(range_match.group(2))
            
            # Handle "< max"
            elif '<' in range_str:
                num_match = re.search(r'(\d+(?:\.\d+)?)', range_str)
                if num_match:
                    max_val = float(num_match.group(1))
            
            # Handle "> min"
            elif '>' in range_str:
                num_match = re.search(r'(\d+(?:\.\d+)?)', range_str)
                if num_match:
                    min_val = float(num_match.group(1))
            
            # Check Normality
            if min_val != float('-inf') or max_val != float('inf'):
                is_norm = (val >= min_val and val <= max_val)
                item['is_normal'] = is_norm
                
        except Exception as e:
            # On error, leave as is or set null
            # item['is_normal'] = None
            pass
            
    return medical_data

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

def process_page_with_llm(page_text, page_idx, total_pages):
    """
    Process a single page using Self-Prompting strategy:
    1. Analyze the page (Structure, Row Count)
    2. Generate Custom Prompt
    3. Extract Data
    """
    debug_logs = []
    
    # Step 1: Analysis
    analysis_prompt = get_report_analysis_prompt(page_idx, total_pages)
    
    # Run Analysis LLM Call
    try:
        response_analysis = ollama_client.chat.completions.create(
            model=Config.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise medical report analyzer. Output valid JSON only."},
                {"role": "user", "content": f"PAGE TEXT:\n{page_text}\n\n{analysis_prompt}"}
            ],
            temperature=0.1,
            max_tokens=2000
        )
        analysis_content = response_analysis.choices[0].message.content.strip()
        debug_logs.append({
            "step": "1_analysis",
            "page": page_idx,
            "prompt_preview": analysis_prompt[:200] + "...",
            "response": analysis_content
        })
        
        # Parse Analysis
        if "```json" in analysis_content:
            analysis_content = analysis_content.split("```json")[1].split("```")[0].strip()
        elif "```" in analysis_content:
            analysis_content = analysis_content.split("```")[1].split("```")[0].strip()
            
        analysis_json = json.loads(analysis_content)
        
    except Exception as e:
        print(f"Analysis failed for page {page_idx}: {e}")
        debug_logs.append({"step": "1_analysis_error", "error": str(e)})
        # Fallback analysis
        analysis_json = {"total_test_rows": 20, "report_language": "Unknown"}

    # Step 2: Extraction
    extraction_prompt = get_custom_extraction_prompt(analysis_json, page_idx, total_pages)
    
    try:
        response_extract = ollama_client.chat.completions.create(
            model=Config.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise medical data extractor. Output valid JSON only."},
                {"role": "user", "content": f"PAGE TEXT:\n{page_text}\n\n{extraction_prompt}"}
            ],
            temperature=0.1,
            max_tokens=4000
        )
        extract_content = response_extract.choices[0].message.content.strip()
        debug_logs.append({
            "step": "2_extraction",
            "page": page_idx,
            "prompt_preview": extraction_prompt[:200] + "...",
            "response": extract_content
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
            files = request.files.getlist('file')
            
            if not files:
                 return {"error": "No files provided."}, 400
                 
            print(f"Processing {len(files)} files...")
            
            page_global_idx = 1
            
            for uploaded_file in files:
                print(f"Processing file: {uploaded_file.filename}")
    
                if uploaded_file.filename.lower().endswith('.pdf'):
                    # Process multi-page PDF files
                    # Use stream=uploaded_file.read() to load the file into memory for PyMuPDF
                    file_content = uploaded_file.read()
                    pdf_document = fitz.open(stream=file_content, filetype="pdf")
                    
                    print(f"PDF has {len(pdf_document)} pages")
                    
                    for page_num in range(len(pdf_document)):
                        page = pdf_document[page_num]
                        
                        # Try direct text extraction first
                        text = page.get_text()
                        
                        # Check heuristics for OCR fallback:
                        # 1. Arabic content (PyMuPDF isn't great with RTL)
                        has_arabic = bool(re.search(r'[\u0600-\u06FF]', text))
                        
                        # 2. Check for images on page (Hybrid PDFs often have text headers but image tables)
                        # get_images() returns list of images on page
                        has_images = len(page.get_images()) > 0
                        
                        # 3. Text length - if huge amount of text (>800), it's likely a full native PDF
                        # If minimal text (<800), it might just be headers/footers with an image body
                        
                        # FORCE OCR if:
                        # - Contains Arabic (Safety)
                        # - Has Images AND text is not overwhelming (Hybrid case)
                        # - Text is very short (Scanned/Image-only)
                        
                        should_use_ocr = False
                        reason = ""
                        
                        if has_arabic:
                            should_use_ocr = True
                            reason = "contains Arabic"
                        elif len(text.strip()) < 800:
                             should_use_ocr = True
                             reason = "low text count (< 800 chars)"
                             # If it has images, it's almost certainly a hybrid/scanned PDF
                             if has_images:
                                 reason += " + has images"
                        
                        
                        if should_use_ocr:
                            print(f"Page {page_global_idx}: {reason}, using OCR...")
                            
                            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0)) # 2x zoom for better OCR
                            img_data = pix.tobytes("png")
                            # Use paragraph=True to group text into lines/blocks, preserving table row structure better
                            result = reader.readtext(img_data, detail=0, paragraph=True)
                            page_text = "\n".join(result)
                            extracted_text += f"\n--- Page {page_global_idx} ---\n{page_text}\n"
                        else:
                            print(f"Page {page_global_idx}: Native PDF extraction ({len(text)} chars)")
                            extracted_text += f"\n--- Page {page_global_idx} ---\n{text}\n"
                        
                        page_global_idx += 1
                            
                elif uploaded_file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    # Process image files using easyocr
                    print(f"Processing image file {uploaded_file.filename} with OCR...")
                    # Use paragraph=True here as well
                    result = reader.readtext(uploaded_file.read(), detail=0, paragraph=True)
                    page_text = "\n".join(result)
                    extracted_text += f"\n--- Page {page_global_idx} ---\n{page_text}\n"
                    page_global_idx += 1
                else:
                    return {"error": "Unsupported file type. Please upload a PDF or image."}, 400


            # --- PER-PAGE SELF-PROMPTING EXTRACTION ---
            
            # 1. Identify valid pages from extracted_text
            # We used "--- Page X ---" delimiter in extraction loop
            # Split text by pages
            pages = extracted_text.split("--- Page ")
            # Filter empty splits and reconstruction
            clean_pages = []
            for p in pages:
                if not p.strip(): continue
                # p starts with "X ---\nText..."
                try:
                    header, content = p.split("---\n", 1)
                    page_num = int(header.strip())
                    clean_pages.append((page_num, content))
                except:
                    continue
            
            total_pages_count = len(clean_pages)
            print(f"Detected {total_pages_count} pages for processing.")
            
            aggregated_medical_data = []
            final_personal_info = {}
            all_debug_logs = []
            
            # 2. Process Each Page
            for page_idx, page_text in clean_pages:
                print(f"Processing Page {page_idx}/{total_pages_count} with LLM...")
                
                extracted_data, logs = process_page_with_llm(page_text, page_idx, total_pages_count)
                all_debug_logs.extend(logs)
                
                if extracted_data:
                    # Merge Medical Data
                    if 'medical_data' in extracted_data and isinstance(extracted_data['medical_data'], list):
                        aggregated_medical_data.extend(extracted_data['medical_data'])
                    
                    # Merge/Update Personal Info (Take the most complete one)
                    # For simplicity, if we find non-empty personal info, we update
                    p_info = extracted_data.get('patient_info', {}) or extracted_data.get('personal_info', {})
                    
                    # Update if current is empty or new one has more keys
                    if not final_personal_info:
                        final_personal_info = p_info
                    elif p_info.get('patient_name'):
                        # If new page has a name, it might be better, or we might want to keep first page.
                        # Usually page 1 is best for personal info.
                        # Let's keep Page 1 info unless empty
                        if not final_personal_info.get('patient_name'):
                            final_personal_info = p_info

            # 3. Post-Processing
            
            # 3a. Self-Correction (LLM Pass) - Requested by user to ensure 100% accuracy
            aggregated_medical_data = verify_and_correct_with_llm(aggregated_medical_data, extracted_text)

            # 3b. Recalculate Normality (Programmatic Math Check)
            # Re-enabled to fix "is_normal" accuracy issues (User: "showing everything as normal")
            aggregated_medical_data = recalculate_normality(aggregated_medical_data)
            
            # Deduplicate - DISABLED based on user request ("return data AS IT IS")
            # aggregated_medical_data = deduplicate_medical_data(aggregated_medical_data)
            
            # Normalize Gender
            if 'patient_gender' in final_personal_info:
                final_personal_info['patient_gender'] = normalize_gender(final_personal_info['patient_gender'])

            # Construct Final Response
            final_response = {
                "personal_info": final_personal_info,
                "medical_info": aggregated_medical_data, # Return list directly for frontend compatibility
                "medical_data": aggregated_medical_data, # Backup key
                "debug_metadata": {
                    "total_pages_processed": total_pages_count,
                    "model_used": Config.OLLAMA_MODEL,
                    "logs": all_debug_logs
                }
            }
            
            return final_response, 200

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": f"Failed to process file: {str(e)}"}, 500
