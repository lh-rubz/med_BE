
import sys
import os

# Add the project root to sys.path
sys.path.append(r'd:\med_BE')

from utils.medical_data_postprocessor import MedicalDataPostProcessor

def test_shifting_detection():
    # Simulate a shifted entry where value matches range boundary
    shifted_entry = {
        "field_name": "Platelet Crit",
        "field_value": "0.1",
        "field_unit": "%",
        "normal_range": "(0.1-0.28)",
        "notes": ""
    }
    
    # Process the entry
    cleaned_entry = MedicalDataPostProcessor._clean_medical_entry(shifted_entry)
    
    # Verify alignment check was added
    print(f"Original notes: '{shifted_entry['notes']}'")
    print(f"Cleaned notes: '{cleaned_entry['notes']}'")
    
    if "check_alignment" in cleaned_entry['notes']:
        print("✅ SUCCESS: 1-off error detected and flagged.")
    else:
        print("❌ FAILURE: 1-off error NOT detected.")

if __name__ == "__main__":
    test_shifting_detection()
