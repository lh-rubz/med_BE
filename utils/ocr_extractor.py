"""OCR Extractor utility for medical report processing."""

import io
from PIL import Image

# Global OCR reader instance (lazy-loaded)
_ocr_reader = None


def get_ocr_instance(languages=None):
    """
    Get the EasyOCR reader instance from vlm_routes.
    The reader supports English and Arabic by default.
    
    Args:
        languages (list): Language codes (ignored - uses default reader)
        
    Returns:
        OCRExtractor: An OCR extractor instance
    """
    return OCRExtractor()


class OCRExtractor:
    """Wrapper around EasyOCR reader for consistent text extraction."""
    
    def __init__(self, languages=None):
        """
        Initialize the OCR extractor.
        Uses the global reader from vlm_routes.
        
        Args:
            languages (list): Ignored - uses default reader
        """
        self.languages = languages or ['en', 'ar']
    
    def extract_text(self, image_data):
        """
        Extract text from image data (bytes).
        
        Args:
            image_data (bytes): Image data in bytes
            
        Returns:
            str: Extracted text
        """
        try:
            # Import here to avoid circular imports and lazy-load issues
            from routes.vlm_routes import get_reader
            
            reader = get_reader()
            
            # Convert bytes to PIL Image
            img = Image.open(io.BytesIO(image_data))
            
            # Read text from image
            results = reader.readtext(img, detail=0)
            
            # Join text into a single string
            text = '\n'.join(results)
            
            return text
        except Exception as e:
            print(f"Error extracting text with OCR: {e}")
            import traceback
            traceback.print_exc()
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
            # Import here to avoid circular imports
            from routes.vlm_routes import get_reader
            
            reader = get_reader()
            
            # Read text from file
            results = reader.readtext(file_path, detail=0)
            
            # Join text into a single string
            text = '\n'.join(results)
            
            return text
        except Exception as e:
            print(f"Error extracting text from file: {e}")
            import traceback
            traceback.print_exc()
            return ""

