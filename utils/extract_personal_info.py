import re
import spacy
from typing import Dict

# Load spaCy model for Named Entity Recognition (NER)
nlp = spacy.load("en_core_web_sm")

def extract_personal_info(text: str) -> Dict[str, str]:
    """
    Extract personal information from the given text.

    Args:
        text (str): The medical report text.

    Returns:
        Dict[str, str]: Extracted personal information.
    """
    personal_info = {}

    # Use spaCy for NER
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            personal_info["Name"] = ent.text
        elif ent.label_ == "DATE":
            personal_info["Date of Birth"] = ent.text
        elif ent.label_ == "GPE":
            personal_info["Location"] = ent.text

    # Use regex for specific patterns
    email_pattern = r'[\w.-]+@[\w.-]+\.\w{2,3}'
    phone_pattern = r'\b\d{10}\b|\(\d{3}\) \d{3}-\d{4}'
    
    # Arabic/English Doctor Name patterns
    # Matches "Dr." or "Doctor" followed by English name
    # OR "د." or "دكتور" followed by Arabic characters
    doctor_pattern_en = r'(?i)(?:Dr\.?|Doctor)\s+([A-Za-z\s]+)'
    doctor_pattern_ar = r'(?:د\.|دكتور)\s+([\u0600-\u06FF\s]+)'

    email_match = re.search(email_pattern, text)
    phone_match = re.search(phone_pattern, text)
    doctor_match_en = re.search(doctor_pattern_en, text)
    doctor_match_ar = re.search(doctor_pattern_ar, text)

    if email_match:
        personal_info["Email"] = email_match.group(0)
    if phone_match:
        personal_info["Phone"] = phone_match.group(0)
    
    # Prioritize Arabic doctor name if found (as requested by user to keep it in Arabic)
    if doctor_match_ar:
        personal_info["Doctor Name"] = doctor_match_ar.group(1).strip()
    elif doctor_match_en:
        personal_info["Doctor Name"] = doctor_match_en.group(1).strip()
    
    # Also attempt to find Patient Name in Arabic if English NER failed or as supplement
    # Pattern: "الاسم:" or "Name:" followed by Arabic text
    name_pattern_ar = r'(?:الاسم|Name)\s*[:\-]\s*([\u0600-\u06FF\s]+)'
    name_match_ar = re.search(name_pattern_ar, text)
    
    if name_match_ar and "Name" not in personal_info:
        personal_info["Name"] = name_match_ar.group(1).strip()
        
    return personal_info

def extract_medical_data(text: str) -> Dict[str, Dict[str, str]]:
    """
    Extract medical data from the given text.

    Args:
        text (str): The medical report text.

    Returns:
        Dict[str, Dict[str, str]]: Extracted medical data with fields like value, normal range, and is_normal.
    """
    medical_data = {}

    # Example patterns for medical data extraction
    # Pattern 1: Field: Value (Range) - Requires colon
    lab_result_pattern = r'(?P<field>[\w\s%]+):\s*(?P<value>[\d\.\*]+)?\s*(?:\((?P<normal_range>[\d\.\-]+)?\))?'
    
    # Pattern 2: Table row style (Field Value Range) - No colon, but stricter structure
    # Looks for: Text (at least 2 chars) + Space + Number + Space + Range (optional)
    # Avoids matching random text by requiring specific structure
    table_row_pattern = r'(?P<field>[A-Za-z][\w\s%]{2,})\s+(?P<value>[\d\.]+\*?)\s+(?P<normal_range>[\d\.]+\s*-\s*[\d\.]+|[<>]\s*[\d\.]+)?'

    # Collect all matches from both patterns
    all_matches = []
    for match in re.finditer(lab_result_pattern, text, re.IGNORECASE):
        all_matches.append(match)
    
    # Only try table pattern if we didn't find many matches with colon pattern, or as supplement
    for match in re.finditer(table_row_pattern, text, re.IGNORECASE):
        # Avoid duplicates or overlapping matches if needed, but for now just add them
        # Simple check: if the field name is already matched, maybe skip? 
        # But same test can appear twice. Let's just add.
        all_matches.append(match)

    for match in all_matches:
        field = match.group("field").strip()
        # Clean up field name (remove trailing/leading whitespace)
        field = re.sub(r'\s+', ' ', field)
        
        value = match.group("value")
        normal_range = match.group("normal_range")

        # Skip fields where both value and normal range are missing
        if not value and not normal_range:
            continue

        # Determine is_normal based on value and normal range
        is_normal = "-"
        if value and normal_range:
            try:
                # Clean value and convert to float
                clean_value = value.replace("*", "").replace("<", "").replace(">", "").strip()
                value_float = float(clean_value)

                # Parse normal range
                lower_bound = float('-inf')
                upper_bound = float('inf')
                
                # Handle "< 5.0" or "> 5.0" formats
                if "<" in normal_range:
                    upper_bound = float(normal_range.replace("<", "").strip())
                elif ">" in normal_range:
                    lower_bound = float(normal_range.replace(">", "").strip())
                elif "-" in normal_range:
                    range_parts = normal_range.split("-")
                    if len(range_parts) == 2:
                        lower_bound = float(range_parts[0].strip())
                        upper_bound = float(range_parts[1].strip())
                
                # Check if normal
                if lower_bound != float('-inf') or upper_bound != float('inf'):
                    is_normal = "Yes" if lower_bound <= value_float <= upper_bound else "No"
                    
            except ValueError:
                is_normal = "-"

        # Add field to medical_data
        medical_data[field] = {
            "value": value if value else "",
            "normal_range": normal_range if normal_range else "-",
            "is_normal": is_normal
        }

    return medical_data

# Example usage
if __name__ == "__main__":
    sample_text = """
    Patient Name: John Doe
    Date of Birth: January 1, 1980
    Address: 123 Main Street, Springfield
    Phone: (123) 456-7890
    Email: john.doe@example.com
    """

    extracted_info = extract_personal_info(sample_text)
    extracted_medical_data = extract_medical_data(sample_text)

    for key, value in extracted_info.items():
        print(f"{key}: {value}")
    for key, value in extracted_medical_data.items():
        print(f"{key}: {value}")