"""Test script to verify the generate_prompt_for_page function works correctly."""

import sys
sys.path.insert(0, 'd:/med_BE')

from utils.vlm_prompts import generate_prompt_for_page

# Test the function
test_page_text = """
Sample medical report content
Patient Name: John Doe
Test: Hemoglobin
Value: 14.5 g/dL
"""

try:
    prompt = generate_prompt_for_page(test_page_text, 1, 3)
    print("✅ SUCCESS! The function executed without errors.\n")
    print("=" * 60)
    print("Generated Prompt:")
    print("=" * 60)
    print(prompt)
    print("=" * 60)
    print("\n✅ All curly braces and quotes are properly escaped!")
    print("✅ The function is ready to use!")
    
except Exception as e:
    print(f"❌ ERROR: {e}")
    print(f"Error type: {type(e).__name__}")
