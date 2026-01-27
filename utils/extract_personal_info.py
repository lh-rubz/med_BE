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
    for key, value in extracted_info.items():
        print(f"{key}: {value}")