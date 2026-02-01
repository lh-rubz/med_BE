
import sys
import os

# Add local directory to path to import utils
sys.path.append(os.getcwd())

from utils.medical_validator import MedicalValidator
from utils.vlm_extraction_validator import validate_and_clean_extraction

# Mock data simulating VLM output with issues
mock_data = {
    "medical_data": [
        {
            "field_name": "Hemoglobin",
            "field_value": "13.5",
            "field_unit": "g/dL",
            "normal_range": "12-16 g/dL",  # Issue: Unit in range
            "is_normal": True # Issue: Defaults to true?
        },
        {
            "field_name": "WBC",
            "field_value": "15.0", # High
            "field_unit": "K/uL", 
            "normal_range": "4.0-11.0",
            "is_normal": None # Should calculate to False
        },
        {
            "field_name": "RBC",
            "field_value": "4.5",
            "field_unit": "M/uL",
            "normal_range": "4.0 - 5.5",
            "is_normal": True
        }
    ]
}

print("--- Original Data ---")
for item in mock_data['medical_data']:
    print(item)

# Run validation
validated_data = MedicalValidator.post_process_extraction(mock_data)

print("\n--- Validated Data ---")
for item in validated_data['medical_data']:
    print(item)

