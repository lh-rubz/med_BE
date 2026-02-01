import re

# Read the file
with open(r'd:\med_BE\routes\vlm_routes.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the function and replace it
output_lines = []
i = 0
while i < len(lines):
    # Check if this is the start of generate_prompt_for_page
    if 'def generate_prompt_for_page(page_text, page_idx, total_pages):' in lines[i]:
        # Found it! Skip to the end of this function
        # The function ends at line 413 (or when we hit the next def)
        output_lines.append('def generate_prompt_for_page(page_text, page_idx, total_pages):\n')
        output_lines.append('    """\n')
        output_lines.append('    Generate a strict and precise prompt for the model based on the page content.\n')
        output_lines.append('    """\n')
        output_lines.append('    return f"""\n')
        output_lines.append('    TASK: Extract medical data from the report page.\n')
        output_lines.append('\n')
        output_lines.append('    PAGE INDEX: {page_idx}/{total_pages}\n')
        output_lines.append('\n')
        output_lines.append('    PAGE CONTENT:\n')
        output_lines.append('    {page_text}\n')
        output_lines.append('\n')
        output_lines.append('    INSTRUCTIONS:\n')
        output_lines.append('    1. Group data by sections (e.g., Haematology Report, Biochemistry).\n')
        output_lines.append('    2. Extract all medical fields with their values, units, and normal ranges.\n')
        output_lines.append('    3. Extract doctor names and ensure they are complete.\n')
        output_lines.append('    4. For each field, calculate and set "is_normal" based on the value and range.\n')
        output_lines.append('    5. Ensure all extracted data is accurate and matches the page content.\n')
        output_lines.append('    6. Handle both Arabic and English text correctly.\n')
        output_lines.append('\n')
        output_lines.append('    OUTPUT FORMAT:\n')
        output_lines.append('    {{{{\n')
        output_lines.append('        "sections": [\n')
        output_lines.append('            {{{{\n')
        output_lines.append('                "section_name": "Haematology Report",\n')
        output_lines.append('                "fields": [\n')
        output_lines.append('                    {{{{\n')
        output_lines.append('                        "field_name": "",\n')
        output_lines.append('                        "field_value": "",\n')
        output_lines.append('                        "field_unit": "",\n')
        output_lines.append('                        "normal_range": "",\n')
        output_lines.append('                        "is_normal": null,\n')
        output_lines.append('                        "notes": ""\n')
        output_lines.append('                    }}}}\n')
        output_lines.append('                ]\n')
        output_lines.append('            }}}}\n')
        output_lines.append('        ],\n')
        output_lines.append('        "doctor_names": ""\n')
        output_lines.append('    }}}}\n')
        output_lines.append('    """\n')
        output_lines.append('\n')
        
        # Skip all lines until we find the next function definition
        i += 1
        while i < len(lines):
            if lines[i].startswith('def ') and 'generate_prompt_for_page' not in lines[i]:
                # Found the next function, don't skip this line
                break
            i += 1
        continue
    
    output_lines.append(lines[i])
    i += 1

# Write back
with open(r'd:\med_BE\routes\vlm_routes.py', 'w', encoding='utf-8') as f:
    f.writelines(output_lines)

print("✅ File updated successfully!")
print(f"Total lines: {len(lines)} -> {len(output_lines)}")
