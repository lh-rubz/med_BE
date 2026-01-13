"""
EasyOCR-based text extraction for medical reports
Provides accurate multilingual OCR with privacy (100% local processing)
"""
# import easyocr (moved to lazy import)
import io
from PIL import Image
from typing import List, Dict, Tuple, Optional
import re
from datetime import datetime


class MedicalOCR:
    """Multilingual OCR for medical reports with Arabic support"""
    
    def __init__(self, languages=['ar', 'en'], gpu=False):
        """
        Initialize OCR reader
        
        Args:
            languages: List of language codes (default: Arabic + English)
            gpu: Use GPU if available (default: False)
        """
        print(f"🔧 Initializing EasyOCR with languages: {languages}")
        try:
            import easyocr
            self.reader = easyocr.Reader(languages, gpu=gpu)
            print("✅ EasyOCR initialized successfully")
        except ImportError:
            print("❌ EasyOCR not found. OCR functionality will be disabled.")
            self.reader = None
    
    def extract_text(self, image_data: bytes) -> str:
        """
        Extract all text from image
        
        Args:
            image_data: Image bytes
            
        Returns:
            Extracted text as string
        """
        try:
            # Convert bytes to PIL Image
            image = Image.open(io.BytesIO(image_data))
            
            # Perform OCR
            if not self.reader:
                return ""
            results = self.reader.readtext(image)
            
            # Combine all detected text
            full_text = '\n'.join([detection[1] for detection in results])
            
            return full_text
        except Exception as e:
            print(f"❌ OCR extraction error: {e}")
            return ""
    
    def extract_with_positions(self, image_data: bytes, min_confidence: float = 0.3) -> List[Dict]:
        """
        Extract text with bounding box positions and confidence
        
        Args:
            image_data: Image bytes
            min_confidence: Minimum confidence threshold (0-1)
            
        Returns:
            List of detections with bbox, text, and confidence
        """
        try:
            image = Image.open(io.BytesIO(image_data))
            results = self.reader.readtext(image)
            
            detections = []
            for bbox, text, confidence in results:
                if confidence >= min_confidence:
                    detections.append({
                        'bbox': bbox,
                        'text': text,
                        'confidence': confidence
                    })
            
            return detections
        except Exception as e:
            print(f"❌ OCR extraction error: {e}")
            return []
    
    def extract_patient_name(self, image_data: bytes) -> Optional[str]:
        """
        Extract patient name specifically (looks for name patterns)
        
        Args:
            image_data: Image bytes
            
        Returns:
            Patient name or None
        """
        try:
            detections = self.extract_with_positions(image_data, min_confidence=0.5)
            
            # Look for text near "Patient Name" or similar labels
            for detection in detections:
                text = detection['text']
                
                # Check if this line contains patient name label
                if any(keyword in text.lower() for keyword in ['patient name', 'name', 'اسم المريض', 'اسم']):
                    # Get the next detection (likely the actual name)
                    idx = detections.index(detection)
                    if idx + 1 < len(detections):
                        return detections[idx + 1]['text']
            
            return None
        except Exception as e:
            print(f"❌ Patient name extraction error: {e}")
            return None
    
    def extract_structured_data(self, image_data: bytes) -> Dict[str, str]:
        """
        Extract common medical report fields
        
        Args:
            image_data: Image bytes
            
        Returns:
            Dictionary with extracted fields
        """
        try:
            full_text = self.extract_text(image_data)
            
            extracted = {
                'patient_name': '',
                'report_date': '',
                'doctor_name': ''
            }
            
            # Extract patient name
            name_match = re.search(r'(?:Patient Name|اسم المريض)[:\s]+([^\n]+)', full_text, re.IGNORECASE)
            if name_match:
                extracted['patient_name'] = name_match.group(1).strip()
            
            # Extract date
            date_match = re.search(r'(?:Report Date|Date|التاريخ)[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})', full_text, re.IGNORECASE)
            if date_match:
                extracted['report_date'] = date_match.group(1).strip()
            
            # Extract doctor name - try multiple patterns
            doctor_patterns = [
                r'(?:Doctor Name|Dr\.|Ref\. By|الطبيب)[:\s]+([^\n]+)',  # Standard fields
                r'(?:Signature)[:\s]*\n\s*([^\n]+)',  # Near signature
                r'Dr\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',  # Dr. followed by name
            ]
            
            for pattern in doctor_patterns:
                doctor_match = re.search(pattern, full_text, re.IGNORECASE)
                if doctor_match:
                    doctor_name = doctor_match.group(1).strip()
                    # Filter out common non-names
                    if doctor_name and len(doctor_name) > 2 and doctor_name.lower() not in ['signature', 'name', ':']:
                        extracted['doctor_name'] = doctor_name
                        break
            
            # Extract Age (supports English and Arabic)
            age_match = re.search(r'(?:Age|العمر)[:\s]+(\d+)[\s]*(?:Y|Years|Year|yrs|سنة|عام)?', full_text, re.IGNORECASE)
            if age_match:
                extracted['patient_age'] = age_match.group(1).strip()
            
            # Calculate Age from DOB if not found
            if 'patient_age' not in extracted:
                dob_match = re.search(r'(?:Date of Birth|DOB|D\.O\.B|Birth Date|تاريخ الميلاد)[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})', full_text, re.IGNORECASE)
                if dob_match:
                    try:
                        dob_str = dob_match.group(1).strip()
                        dob_date = None
                        # Try common formats
                        for fmt in ['%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%m/%d/%Y']:
                            try:
                                dob_date = datetime.strptime(dob_str, fmt)
                                break
                            except ValueError:
                                continue
                        
                        if dob_date:
                            # Determine reference date (Report Date or Today)
                            ref_date = datetime.now()
                            if extracted.get('report_date'):
                                for fmt in ['%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d']:
                                    try:
                                        ref_date = datetime.strptime(extracted['report_date'], fmt)
                                        break
                                    except ValueError:
                                        continue
                            
                            # Calculate age
                            age = ref_date.year - dob_date.year - ((ref_date.month, ref_date.day) < (dob_date.month, dob_date.day))
                            if age >= 0:
                                extracted['patient_age'] = str(age)
                                print(f"💡 Calculated age from DOB ({dob_str}): {age}")
                    except Exception as e:
                        print(f"⚠️ Failed to calculate age from DOB: {e}")

            # Extract Gender (supports English and Arabic)
            gender_match = re.search(r'(?:Gender|Sex|الجنس)[:\s]+([A-Za-z]+|ذكر|أنثى|انثى)', full_text, re.IGNORECASE)
            if gender_match:
                g = gender_match.group(1).strip().lower()
                if g in ['male', 'm', 'ذكر']:
                    extracted['patient_gender'] = 'Male'
                elif g in ['female', 'f', 'أنثى', 'انثى']:
                    extracted['patient_gender'] = 'Female'
                else:
                    extracted['patient_gender'] = g.capitalize()

            return extracted
        except Exception as e:
            print(f"❌ Structured extraction error: {e}")
            return {'patient_name': '', 'report_date': '', 'doctor_name': ''}


# Global OCR instance (initialized once)
_ocr_instance = None

def get_ocr_instance(languages=['ar', 'en'], gpu=True) -> MedicalOCR:
    """
    Get or create global OCR instance (singleton pattern)
    
    Args:
        languages: List of language codes
        gpu: Use GPU if available (default: True)
        
    Returns:
        MedicalOCR instance
    """
    global _ocr_instance
    
    if _ocr_instance is None:
        _ocr_instance = MedicalOCR(languages=languages, gpu=gpu)
    
    return _ocr_instance
