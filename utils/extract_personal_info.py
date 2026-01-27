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

    email_match = re.search(email_pattern, text)
    phone_match = re.search(phone_pattern, text)

    if email_match:
        personal_info["Email"] = email_match.group(0)
    if phone_match:
        personal_info["Phone"] = phone_match.group(0)

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
    lab_result_pattern = r'(?P<field>[\w\s]+):\s*(?P<value>[\d\.]+)?\s*(?:\(Normal Range:\s*(?P<normal_range>[\d\.\-]+)?\))?\s*(?P<is_normal>is_normal:\s*(Yes|No))?'

    for match in re.finditer(lab_result_pattern, text, re.IGNORECASE):
        field = match.group("field").strip()
        value = match.group("value")
        normal_range = match.group("normal_range")
        is_normal = match.group("is_normal")

        # Only add fields with at least a value or normal range
        if value or normal_range:
            medical_data[field] = {
                "value": value if value else "",
                "normal_range": normal_range if normal_range else "-",
                "is_normal": is_normal.split(":")[-1].strip() if is_normal else "-"
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