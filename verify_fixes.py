
import sys
import os

# Add local directory to path to import utils
sys.path.append(os.getcwd())

from utils.medical_validator import MedicalValidator
from utils.medical_data_postprocessor import MedicalDataPostProcessor

def test_empty_row_skipping():
    print("\n--- Testing Empty Row Skipping ---")
    mock_data = {
        "medical_data": [
            {"field_name": "Glucose", "field_value": "100", "field_unit": "mg/dL", "normal_range": "70-110"},
            {"field_name": "Empty Test", "field_value": "", "field_unit": "", "normal_range": ""},
            {"field_name": "Spacer", "field_value": "*", "field_unit": "", "normal_range": ""},
            {"field_name": "Phantm", "field_value": "EMPTY_SPECIFIED", "field_unit": "", "normal_range": "10-20"}
        ]
    }
    cleaned = MedicalDataPostProcessor.clean_extracted_data(mock_data)
    print(f"Extracted rows: {len(cleaned['medical_data'])}")
    for item in cleaned['medical_data']:
        print(f" - {item['field_name']}: {item['field_value']}")
    assert len(cleaned['medical_data']) == 1
    assert cleaned['medical_data'][0]['field_name'] == "Glucose"

def test_typo_fixes():
    print("\n--- Testing Typo Fixes ---")
    mock_data = {
        "medical_data": [
            {"field_name": "Cholesterol, Tota", "field_value": "200"},
            {"field_name": "(GPTI", "field_value": "30"},
            {"field_name": "M.C.V", "field_value": "90"},
            {"field_name": "Lymphocytes/ ", "field_value": "25"}
        ]
    }
    cleaned = MedicalDataPostProcessor.clean_extracted_data(mock_data)
    for item in cleaned['medical_data']:
        print(f" - {item['field_name']}")
    
    names = [item['field_name'] for item in cleaned['medical_data']]
    assert "Cholesterol, Total" in names
    assert "(GPT)" in names
    assert "MCV" in names
    assert "Lymphocytes" in names

def test_range_hygiene():
    print("\n--- Testing Range Hygiene & Categorical is_normal ---")
    fields = [
        {
            "field_name": "Hemoglobin",
            "field_value": "13.5",
            "field_unit": "g/dL",
            "normal_range": "12-16 g/dL"
        },
        {
            "field_name": "HbA1c",
            "field_value": "6.0",
            "field_unit": "%",
            "normal_range": "Normal: < 5.7, Prediabetes: 5.7-6.4, Diabetes: > 6.5"
        }
    ]
    
    for f in fields:
        validated = MedicalValidator.validate_and_normalize_field(f)
        print(f"Name: {validated['field_name']}")
        print(f" - Cleaned Range: '{validated['normal_range']}'")
        print(f" - Is Normal: {validated['is_normal']}")
        
        if validated['field_name'] == "Hemoglobin":
            assert validated['normal_range'] == "12-16"
            assert validated['is_normal'] is True
        if validated['field_name'] == "HbA1c":
            assert validated['is_normal'] is False # Prediabetes is False

if __name__ == "__main__":
    try:
        test_empty_row_skipping()
        test_typo_fixes()
        test_range_hygiene()
        print("\n✅ ALL TESTS PASSED!")
    except AssertionError as e:
        print(f"\n❌ TEST FAILED!")
        raise e
