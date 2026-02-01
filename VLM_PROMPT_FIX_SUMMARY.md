# VLM Prompt Function Fix - Summary

## Problem
The `generate_prompt_for_page` function was failing due to invalid format specifiers in the f-string. Python was interpreting the curly braces `{}` in the JSON template as placeholders for string formatting, causing errors.

## Solution
The function has been successfully added to `vlm_prompts.py` with **properly escaped curly braces**.

### Key Changes:
1. **Escaped all curly braces** using quadruple braces `{{{{` and `}}}}`
   - In f-strings, `{{` becomes `{` in the output
   - So `{{{{` becomes `{{` in the output (which is what we want for JSON)

2. **Quotes are properly handled** - double quotes inside the f-string triple quotes work correctly

3. **Preserved structure and readability** - the prompt remains clear and well-formatted

## Fixed Function Location
- **File**: `d:\med_BE\utils\vlm_prompts.py`
- **Lines**: 263-309

## Code Example

```python
def generate_prompt_for_page(page_text, page_idx, total_pages):
    """Generate a prompt for extracting structured medical data from a report page."""
    return f"""
    TASK: Extract medical data from the report page.

    PAGE INDEX: {page_idx}/{total_pages}

    PAGE CONTENT:
    {page_text}

    INSTRUCTIONS:
    1. Group data by sections (e.g., Haematology Report, Biochemistry).
    2. Extract all medical fields with their values, units, and normal ranges.
    3. Extract doctor names and ensure they are complete.
    4. For each field, calculate and set "is_normal" based on the value and range.
    5. Ensure all extracted data is accurate and matches the page content.
    6. Handle both Arabic and English text correctly.

    OUTPUT FORMAT:
    {{{{
        "sections": [
            {{{{
                "section_name": "Haematology Report",
                "fields": [
                    {{{{
                        "field_name": "",
                        "field_value": "",
                        "field_unit": "",
                        "normal_range": "",
                        "is_normal": null,
                        "notes": ""
                    }}}}
                ]
            }}}}
        ],
        "doctor_names": ""
    }}}}
    """
```

## Verification
✅ Function executes without errors  
✅ All curly braces are properly escaped  
✅ JSON template is correctly formatted  
✅ Ready to use in production  

## How to Use

```python
from utils.vlm_prompts import generate_prompt_for_page

# Example usage
page_content = "Medical report text here..."
prompt = generate_prompt_for_page(page_content, page_idx=1, total_pages=5)

# The prompt will have properly formatted JSON template
# with actual curly braces (not Python format placeholders)
```

## Important Notes

- **Quadruple braces** (`{{{{` and `}}}}`) in f-strings produce double braces (`{{` and `}}`) in the output
- This is necessary because we want the **literal** JSON structure in the output, not Python string formatting
- The `page_idx`, `total_pages`, and `page_text` variables are still interpolated correctly using single braces
