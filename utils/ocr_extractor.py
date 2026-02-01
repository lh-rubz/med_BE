"""OCR Extractor utility for medical report processing."""

import easyocr
import io
from PIL import Image

# Global OCR reader instances for different language combinations
_ocr_readers = {}


def get_ocr_instance(languages=None):
    """
    Get or create an EasyOCR reader instance for the specified languages.
    
    Args:
        languages (list): List of language codes (e.g., ['en', 'ar'])
        
    Returns:
        OCRExtractor: An OCR extractor instance
    """
    if languages is None:
        languages = ['en', 'ar']
    
    # Create a hashable key from the languages list
    lang_key = tuple(sorted(languages))
    
    # Return cached reader if available
    if lang_key not in _ocr_readers:
        _ocr_readers[lang_key] = OCRExtractor(languages)
    
    return _ocr_readers[lang_key]


class OCRExtractor:
    """Wrapper around EasyOCR reader for consistent text extraction."""
    
    def __init__(self, languages=None):
        """
        Initialize the OCR extractor.
        
        Args:
            languages (list): List of language codes (default: ['en', 'ar'])
        """
        if languages is None:
            languages = ['en', 'ar']
        
        self.languages = languages
        self.reader = easyocr.Reader(languages, gpu=False)  # gpu=False for compatibility
    
    def extract_text(self, image_data):
        """
        Extract text from image data (bytes).
        
        Args:
            image_data (bytes): Image data in bytes
            
        Returns:
            str: Extracted text
        """
        try:
            # Convert bytes to PIL Image
            img = Image.open(io.BytesIO(image_data))
            
            # Read text from image
            results = self.reader.readtext(img, detail=0)
            
            # Join text into a single string
            text = '\n'.join(results)
            
            return text
        except Exception as e:
            print(f"Error extracting text with OCR: {e}")
            return ""
    
    def extract_text_from_file(self, file_path):
        """
        Extract text from an image file.
        
        Args:
            file_path (str): Path to the image file
            
        Returns:
            str: Extracted text
        """
        try:
            # Read text from file
            results = self.reader.readtext(file_path, detail=0)
            
            # Join text into a single string
            text = '\n'.join(results)
            
            return text
        except Exception as e:
            print(f"Error extracting text from file: {e}")
            return ""
