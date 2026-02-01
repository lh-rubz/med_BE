import re

def extract_personal_info(report_text):
    """
    Extract personal information such as patient name, age, gender, and doctor name from the report text.
    """
    personal_info = {}

    # Extract patient name
    name_match = re.search(r'Patient Name\s*:\s*(.+)', report_text)
    if name_match:
        personal_info['patient_name'] = name_match.group(1).strip()

    # Extract age and gender
    age_gender_match = re.search(r'Gender & Age\s*:\s*(.+)', report_text)
    if age_gender_match:
        age_gender = age_gender_match.group(1).strip()
        if ',' in age_gender:
            gender, age = age_gender.split(',', 1)
            personal_info['patient_gender'] = gender.strip()
            personal_info['patient_age'] = age.strip()

    # Extract doctor name
    doctor_match = re.search(r'Doctor Name\s*:\s*(.+)', report_text)
    if doctor_match:
        personal_info['doctor_name'] = doctor_match.group(1).strip()

    return personal_info

def extract_medical_data(report_text):
    """
    Extract medical data fields such as field name, value, unit, and normal range from the report text.
    """
    medical_data = []

    # Regex to match medical fields
    field_pattern = re.compile(
        r'(?P<field_name>.+?)\s*:\s*(?P<field_value>[\d\.<>]+)\s*(?P<field_unit>\w+/\w+|\w+)?\s*(?P<normal_range>.+)?'
    )

    for match in field_pattern.finditer(report_text):
        field = {
            'field_name': match.group('field_name').strip(),
            'field_value': match.group('field_value').strip(),
            'field_unit': match.group('field_unit').strip() if match.group('field_unit') else None,
            'normal_range': match.group('normal_range').strip() if match.group('normal_range') else None,
        }
        medical_data.append(field)

    return medical_data