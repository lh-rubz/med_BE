"""
Example usage of the Advanced VLM Extraction System.

This file shows practical examples of how to use the new advanced system
in your actual application.
"""

# -*- coding: utf-8 -*-
import sys
import io

# Set UTF-8 encoding for terminal output
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Example 1: Simple validation and correction
# ═══════════════════════════════════════════════════════════════════════════

def example_1_basic_validation():
    """Example: Validate extracted data and fix common issues."""
    from utils.vlm_integration_advanced import VLMExtractionValidator
    
    # This is data extracted by the VLM (might have errors)
    raw_extraction = {
        'patient_name': 'رئيسي خضر طالب خطيب',
        'patient_age': '28',                          # WRONG! Should be ~50
        'patient_dob': '01/05/1975',                  # Needs conversion to YYYY-MM-DD
        'patient_gender': 'ذكر',                      # Arabic, needs conversion to "Male"
        'report_date': '2026-01-23 20:50:51.129476',  # Has timestamp, needs cleaning
        'doctor_names': ''                            # Empty, but should search thoroughly
    }
    
    # Create validator and validate
    validator = VLMExtractionValidator()
    corrected = validator.validate_personal_info(raw_extraction)
    
    print("BEFORE Validation:")
    print(f"  Age: {raw_extraction['patient_age']}")
    # Skip printing Arabic text due to terminal encoding issues
    print(f"  Gender: (Arabic value in raw_extraction)")
    print(f"  DOB: {raw_extraction['patient_dob']}")
    print(f"  Report Date: {raw_extraction['report_date']}")
    
    print("\nAFTER Validation & Correction:")
    print(f"  Age: {corrected['patient_age']} (calculated from DOB)")
    print(f"  Gender: {corrected['patient_gender']} (converted to English)")
    print(f"  DOB: {corrected['patient_dob']} (normalized to YYYY-MM-DD)")
    print(f"  Report Date: {corrected['report_date']} (timestamp removed)")


# Example 2: Full extraction pipeline
# ═══════════════════════════════════════════════════════════════════════════

def example_2_full_pipeline():
    """Example: Complete extraction, validation, and storage pipeline."""
    from utils.vlm_prompts_advanced import get_advanced_personal_info_prompt
    from utils.vlm_integration_advanced import AdvancedVLMExtractor, VLMExtractionValidator
    
    # Suppose we have an image and a VLM client
    # image_data = load_image("report.pdf")
    # vlm_client = initialize_vlm_client()
    
    page_idx = 1
    total_pages = 2
    
    # Step 1: Create prompt for this page
    prompt = get_advanced_personal_info_prompt(page_idx, total_pages)
    # raw_extraction = vlm_client.extract(image_data, prompt)
    # For example, we'll use fake data
    raw_extraction = {
        'patient_name': 'احمد محمد علي',
        'patient_age': '',  # Empty, will calculate from DOB
        'patient_dob': '05/15/1980',
        'patient_gender': 'ذكر',  # Arabic male
        'report_date': '2025-12-31 14:30:00',
        'doctor_names': 'Dr. خالد العثمان'
    }
    
    # Step 2: Validate and correct
    validator = VLMExtractionValidator()
    personal_info = validator.validate_personal_info(raw_extraction)
    
    # Step 3: Create extractor for further processing
    extractor = AdvancedVLMExtractor()
    
    # Step 4: Check if data is valid
    print(f"Extracted from page {page_idx}/{total_pages}:")
    print(f"  Patient: {personal_info['patient_name']}")
    print(f"  Age: {personal_info['patient_age']} (calculated)")
    print(f"  Gender: {personal_info['patient_gender']} (English)")
    print(f"  DOB: {personal_info['patient_dob']} (normalized)")
    print(f"  Report Date: {personal_info['report_date']} (cleaned)")
    print(f"  Doctor: {personal_info['doctor_names']}")
    
    # Step 5: Log extraction
    extractor.log_extraction(page_idx, personal_info, status='success')
    
    # Step 6: Return or save to database
    return personal_info


# Example 3: Medical data extraction with alignment checking
# ═══════════════════════════════════════════════════════════════════════════

def example_3_medical_data_validation():
    """Example: Extract medical data and validate row alignment."""
    from utils.vlm_integration_advanced import AdvancedVLMExtractor, VLMExtractionValidator
    
    # Raw medical data extracted by VLM (might have misalignment issues)
    raw_medical_data = {
        'medical_data': [
            {
                'field_name': 'Fasting Blood Sugar (FBS)',
                'field_value': '109',
                'field_unit': 'mg/dL',
                'normal_range': '(70-110)',
                'is_normal': True,
                'category': 'Chemistry',
                'notes': ''
            },
            {
                'field_name': 'Glucose',
                'field_value': '109%',  # WRONG! Contains unit symbol
                'field_unit': '',
                'normal_range': '(70-110)',
                'is_normal': None,
                'category': 'Chemistry',
                'notes': 'MISALIGNED'
            },
            {
                'field_name': 'ALT',
                'field_value': '320',  # WRONG! Should be 32
                'field_unit': 'U/L',
                'normal_range': '(0-33)',  # Value is 10x larger than range max
                'is_normal': False,
                'category': 'Chemistry',
                'notes': ''
            },
            {
                'field_name': 'WBC',
                'field_value': '',  # Empty
                'field_unit': 'K/uL',
                'normal_range': '(4.6-11)',
                'is_normal': None,
                'category': 'Hematology',
                'notes': ''
            }
        ]
    }
    
    # Create extractor and validator
    extractor = AdvancedVLMExtractor()
    validator = VLMExtractionValidator()
    
    # Process medical data
    result = extractor.process_medical_data(raw_medical_data)
    medical_data = result['medical_data']
    validation = result['validation']
    
    print(f"Medical Data Validation Results:")
    print(f"  Total rows: {validation['total_rows']}")
    print(f"  Rows with values: {validation['rows_with_values']}")
    print(f"  Rows with ranges: {validation['rows_with_ranges']}")
    print(f"  Misaligned rows detected: {len(validation['misaligned_rows'])}")
    
    if validation['misaligned_rows']:
        print(f"  ⚠️  Issues found:")
        for row_idx, reason in validation['misaligned_rows']:
            print(f"     Row {row_idx}: {reason}")
        print(f"  → Need re-extraction with corrective prompt")
    
    # If needs re-extraction
    if extractor.should_reextract(validation):
        print("\n❌ Extraction failed validation, would trigger re-extraction")
    else:
        print("\n✅ Extraction passed validation")


# Example 4: Multi-page report processing
# ═══════════════════════════════════════════════════════════════════════════

def example_4_multipage_report():
    """Example: Process a multi-page report sequentially."""
    from utils.vlm_prompts_advanced import (
        get_advanced_personal_info_prompt,
        get_advanced_medical_data_prompt,
        get_advanced_page_verification_prompt
    )
    from utils.vlm_integration_advanced import AdvancedVLMExtractor, VLMExtractionValidator
    
    # Suppose we have 2 pages
    total_pages = 2
    all_personal_info = None
    all_medical_data = []
    
    for page_idx in range(1, total_pages + 1):
        print(f"\n{'='*60}")
        print(f"Processing page {page_idx} of {total_pages}")
        print(f"{'='*60}")
        
        # Step 1: Extract personal info (should be same on all pages)
        print(f"→ Extracting personal info...")
        personal_prompt = get_advanced_personal_info_prompt(page_idx, total_pages)
        # personal_data = vlm_client.extract(image, personal_prompt)
        # For example:
        personal_data = {
            'patient_name': 'Test Patient',
            'patient_age': '',
            'patient_dob': '01/05/1975',
            'patient_gender': 'ذكر',
            'report_date': '2025-12-31',
            'doctor_names': ''
        }
        
        validator = VLMExtractionValidator()
        personal_info = validator.validate_personal_info(personal_data)
        
        if page_idx == 1:
            all_personal_info = personal_info
        else:
            # Verify consistency on subsequent pages
            if personal_info['patient_name'] != all_personal_info['patient_name']:
                print("⚠️  WARNING: Patient name differs on page 2!")
        
        # Step 2: Extract medical data
        print(f"→ Extracting medical data...")
        medical_prompt = get_advanced_medical_data_prompt(page_idx, total_pages)
        # medical_data = vlm_client.extract(image, medical_prompt)
        # For example:
        medical_data = {
            'medical_data': [
                {'field_name': f'Test {i}', 'field_value': str(100 + i), 
                 'field_unit': 'mg/dL', 'normal_range': f'({80 + i}-{120 + i})', 
                 'is_normal': True, 'category': 'Chemistry', 'notes': ''}
                for i in range(5)  # 5 tests per page
            ]
        }
        
        extractor = AdvancedVLMExtractor()
        result = extractor.process_medical_data(medical_data)
        all_medical_data.extend(result['medical_data'])
        
        # Step 3: Verify page completion
        print(f"→ Verifying page completion...")
        verify_prompt = get_advanced_page_verification_prompt(page_idx, total_pages)
        # verification = vlm_client.extract(image, verify_prompt)
        print(f"  ✓ Page {page_idx} complete")
    
    print(f"\n{'='*60}")
    print(f"FINAL REPORT SUMMARY:")
    print(f"{'='*60}")
    print(f"Patient: {all_personal_info['patient_name']}")
    print(f"Gender: {all_personal_info['patient_gender']}")
    print(f"Age: {all_personal_info['patient_age']}")
    print(f"Total medical tests: {len(all_medical_data)}")
    print(f"Report ready for storage!")


# Example 5: Error recovery and re-extraction
# ═══════════════════════════════════════════════════════════════════════════

def example_5_error_recovery():
    """Example: Detect extraction errors and re-extract with corrections."""
    from utils.vlm_integration_advanced import AdvancedVLMExtractor, VLMExtractionValidator
    from utils.vlm_correction import generate_corrective_prompt, analyze_extraction_issues
    
    # Initial extraction (has errors)
    raw_extraction = {
        'medical_data': [
            {'field_name': 'Test1', 'field_value': '100', 'field_unit': 'mg/dL', 
             'normal_range': '(80-120)', 'is_normal': True, 'category': '', 'notes': ''},
            {'field_name': 'Test2', 'field_value': '200%', 'field_unit': '', 
             'normal_range': '(150-250)', 'is_normal': None, 'category': '', 'notes': ''},
            # Only 2 tests, but table has 20+!
        ]
    }
    
    # Validate
    extractor = AdvancedVLMExtractor()
    result = extractor.process_medical_data(raw_extraction)
    validation = result['validation']
    
    print(f"Initial Extraction Result:")
    print(f"  Rows extracted: {validation['total_rows']}")
    print(f"  Valid: {validation['is_valid']}")
    print(f"  Reason: {validation.get('reason', 'OK')}")
    
    # Check if needs re-extraction
    if extractor.should_reextract(validation):
        print(f"\n❌ Extraction failed! Re-extracting...")
        
        # Analyze issues
        issues = analyze_extraction_issues(raw_extraction)
        print(f"\nIssues detected:")
        for issue in issues['issues'][:5]:
            print(f"  - {issue['type']}: {issue['reason']}")
        
        # Generate corrective prompt
        corrective = generate_corrective_prompt(
            raw_extraction, issues, 
            idx=1, total_pages=1
        )
        
        print(f"\nCorrective prompt generated ({len(corrective)} chars)")
        print(f"Re-extracting with enhanced instructions...\n")
        
        # Second attempt (would use same corrective prompt)
        # raw_extraction_v2 = vlm_client.extract(image, corrective)
        # Assume it succeeds this time:
        raw_extraction_v2 = {
            'medical_data': [
                {'field_name': f'Test{i}', 'field_value': str(100 + i), 
                 'field_unit': 'mg/dL', 'normal_range': f'({80 + i}-{120 + i})', 
                 'is_normal': True, 'category': 'Chemistry', 'notes': ''}
                for i in range(20)  # All 20 rows this time!
            ]
        }
        
        result_v2 = extractor.process_medical_data(raw_extraction_v2)
        validation_v2 = result_v2['validation']
        
        print(f"Second Extraction Result:")
        print(f"  Rows extracted: {validation_v2['total_rows']}")
        print(f"  Valid: {validation_v2['is_valid']}")
        print(f"\n✅ SUCCESS! Re-extraction fixed the issues.")


# Example 6: Full integration in a Flask route
# ═══════════════════════════════════════════════════════════════════════════

def example_6_flask_integration():
    """
    Example: How to integrate the advanced VLM system into your Flask application.
    
    This shows how the code would look in your routes/vlm_routes.py or similar.
    """
    
    # Code that would go in your Flask route:
    route_code = '''
from flask import request, jsonify
from utils.vlm_prompts_advanced import (
    get_advanced_personal_info_prompt,
    get_advanced_medical_data_prompt
)
from utils.vlm_integration_advanced import (
    AdvancedVLMExtractor,
    VLMExtractionValidator
)
from utils.vlm_correction import generate_corrective_prompt, analyze_extraction_issues

@app.route('/api/extract-report', methods=['POST'])
def extract_report():
    """Extract medical report using advanced VLM system."""
    
    # Get uploaded file
    file = request.files['report']
    
    try:
        # Convert PDF/image to pages
        images = convert_to_images(file)
        total_pages = len(images)
        
        all_personal_info = None
        all_medical_data = []
        
        # Process each page
        for page_idx, image_data in enumerate(images, 1):
            # Extract personal info
            prompt = get_advanced_personal_info_prompt(page_idx, total_pages)
            raw_personal = vlm_client.extract(image_data, prompt)
            
            validator = VLMExtractionValidator()
            personal_info = validator.validate_personal_info(raw_personal)
            
            if page_idx == 1:
                all_personal_info = personal_info
            
            # Extract medical data
            prompt = get_advanced_medical_data_prompt(page_idx, total_pages)
            raw_medical = vlm_client.extract(image_data, prompt)
            
            extractor = AdvancedVLMExtractor()
            result = extractor.process_medical_data(raw_medical)
            medical_data = result['medical_data']
            validation = result['validation']
            
            # Re-extract if needed
            if extractor.should_reextract(validation):
                issues = analyze_extraction_issues(raw_medical)
                corrective = generate_corrective_prompt(
                    raw_medical, issues, page_idx, total_pages
                )
                raw_medical = vlm_client.extract(image_data, corrective)
                result = extractor.process_medical_data(raw_medical)
                medical_data = result['medical_data']
            
            all_medical_data.extend(medical_data)
        
        # Save to database
        report = save_report(
            user_id=current_user.id,
            patient_name=all_personal_info['patient_name'],
            patient_gender=all_personal_info['patient_gender'],
            patient_age=all_personal_info['patient_age'],
            patient_dob=all_personal_info['patient_dob'],
            report_date=all_personal_info['report_date'],
            doctor_names=all_personal_info['doctor_names'],
            medical_data=all_medical_data
        )
        
        return jsonify({
            'success': True,
            'report_id': report.id,
            'patient_name': all_personal_info['patient_name'],
            'patient_gender': all_personal_info['patient_gender'],
            'total_tests': len(all_medical_data)
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    '''
    
    print("Flask Route Integration Example:")
    print(route_code)


# Run all examples
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("ADVANCED VLM EXTRACTION SYSTEM - USAGE EXAMPLES")
    print("=" * 70)
    
    print("\n\n" + "=" * 70)
    print("EXAMPLE 1: Basic Validation and Correction")
    print("=" * 70)
    example_1_basic_validation()
    
    print("\n\n" + "=" * 70)
    print("EXAMPLE 2: Full Extraction Pipeline")
    print("=" * 70)
    example_2_full_pipeline()
    
    print("\n\n" + "=" * 70)
    print("EXAMPLE 3: Medical Data Validation")
    print("=" * 70)
    example_3_medical_data_validation()
    
    print("\n\n" + "=" * 70)
    print("EXAMPLE 4: Multi-Page Report Processing")
    print("=" * 70)
    example_4_multipage_report()
    
    print("\n\n" + "=" * 70)
    print("EXAMPLE 5: Error Recovery and Re-Extraction")
    print("=" * 70)
    example_5_error_recovery()
    
    print("\n\n" + "=" * 70)
    print("EXAMPLE 6: Flask Integration Code")
    print("=" * 70)
    example_6_flask_integration()
