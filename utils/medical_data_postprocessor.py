"""
Post-processing utilities for VLM extracted medical data.
Handles validation, cleanup, and structure-aware corrections.
"""
from typing import Dict, List, Any, Optional
import json
import re


class MedicalDataPostProcessor:
    """Post-processes VLM-extracted medical data to ensure quality and consistency."""
    
    @staticmethod
    def clean_extracted_data(
        extracted_data: Dict[str, Any],
        structure_type: str = None,
        strict_validation: bool = True
    ) -> Dict[str, Any]:
        """
        Clean and validate extracted medical data.
        
        Args:
            extracted_data: Raw extracted data from VLM
            structure_type: Report structure type for context-aware processing (optional)
            strict_validation: If True, remove incomplete entries
        
        Returns:
            Cleaned data with invalid entries removed
        """
        
        # Clean report date first (needed for DOB to age calculation)
        cleaned_report_date = MedicalDataPostProcessor._clean_date(extracted_data.get("report_date", ""))
        
        # Clean age - may involve calculating from DOB
        cleaned_age = MedicalDataPostProcessor._clean_age(
            extracted_data.get("patient_age", ""),
            report_date=cleaned_report_date
        )
        
        # Enforce valid report_type categories
        allowed_types = ["Lab results", "Prescriptions", "Imaging", "Cardiology", "Neurology", "Orthopedic"]
        report_type = str(extracted_data.get("report_type", "")).strip()
        best_type = "Lab results"  # Default fallback
        if report_type:
            for allowed in allowed_types:
                if allowed.lower() in report_type.lower() or report_type.lower() in allowed.lower():
                    best_type = allowed
                    break

        cleaned = {
            "patient_name": MedicalDataPostProcessor._clean_patient_name(extracted_data.get("patient_name", "")),
            "patient_age": cleaned_age,
            "patient_gender": MedicalDataPostProcessor._clean_gender(extracted_data.get("patient_gender", "")),
            "report_date": cleaned_report_date,
            "report_name": extracted_data.get("report_name", ""),
            "report_type": best_type,
            "doctor_names": MedicalDataPostProcessor._clean_doctor_name(extracted_data.get("doctor_names", "")),
            "medical_data": []
        }
        
        # Clean medical data entries
        raw_medical_data = extracted_data.get("medical_data", [])
        
        for entry in raw_medical_data:
            cleaned_entry = MedicalDataPostProcessor._clean_medical_entry(
                entry,
                strict_validation=strict_validation
            )
            
            if cleaned_entry:  # Only add if it passes validation
                cleaned["medical_data"].append(cleaned_entry)
        
        # Calculate is_normal for all entries (Gender-aware)
        cleaned["medical_data"] = MedicalDataPostProcessor.add_is_normal_to_entries(
            cleaned["medical_data"],
            patient_gender=cleaned["patient_gender"]
        )
        
        # Deduplicate entries (remove exact duplicates from multi-page extraction)
        cleaned["medical_data"] = MedicalDataPostProcessor._deduplicate_entries(
            cleaned["medical_data"]
        )
        
        # Merge E.S.R sub-rows (I Hour / II Hour) into the parent E.S.R row
        cleaned["medical_data"] = MedicalDataPostProcessor._merge_esr_rows(
            cleaned["medical_data"]
        )
        
        cleaned["total_fields_in_image"] = len(cleaned["medical_data"])
        
        return cleaned
    
    @staticmethod
    def _merge_esr_rows(medical_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Handle E.S.R sub-rows (I Hour, II Hour):
        - Rename them to "E.S.R - I Hour", "E.S.R - II Hour"
        - If parent E.S.R has the value but I Hour is empty, move value to I Hour
        - Remove hour rows that have no value (empty II Hour)
        - Remove the standalone E.S.R parent row (it's just a section header)
        """
        if not medical_data:
            return medical_data
        
        esr_idx = None
        hour_entries = []  # list of (index, name_lower)
        
        for i, entry in enumerate(medical_data):
            name = entry.get('field_name', '').strip().lower()
            if name in ('e.s.r', 'esr', 'e.s.r.', 'erythrocyte sedimentation rate'):
                esr_idx = i
            elif name in ('i hour', 'ii hour', '1 hour', '2 hour', 'i hour (esr)', 'ii hour (esr)'):
                hour_entries.append((i, name))
        
        if not hour_entries:
            return medical_data
        
        indices_to_remove = set()
        
        # Rename hour rows: "I Hour" → "E.S.R - I Hour"
        for hi, _ in hour_entries:
            original_name = medical_data[hi].get('field_name', '').strip()
            if not original_name.upper().startswith('E.S.R'):
                medical_data[hi]['field_name'] = f"E.S.R - {original_name}"
        
        # If parent E.S.R row exists, transfer its data to I Hour if needed
        if esr_idx is not None:
            esr_entry = medical_data[esr_idx]
            esr_value = str(esr_entry.get('field_value', '')).strip()
            
            if esr_value:
                # Find the first hour row (I Hour) and give it the value if it's empty
                for hi, hname in hour_entries:
                    if 'i hour' in hname or '1 hour' in hname:
                        hval = str(medical_data[hi].get('field_value', '')).strip()
                        if not hval:
                            medical_data[hi]['field_value'] = esr_value
                            if not str(medical_data[hi].get('field_unit', '')).strip():
                                medical_data[hi]['field_unit'] = esr_entry.get('field_unit', '')
                            if not str(medical_data[hi].get('normal_range', '')).strip():
                                medical_data[hi]['normal_range'] = esr_entry.get('normal_range', '')
                        break
            
            # Always remove the standalone E.S.R parent row
            indices_to_remove.add(esr_idx)
        
        # Remove hour rows that have no value (e.g., empty II Hour)
        for hi, _ in hour_entries:
            hval = str(medical_data[hi].get('field_value', '')).strip()
            if not hval:
                indices_to_remove.add(hi)
        
        if indices_to_remove:
            medical_data = [e for i, e in enumerate(medical_data) if i not in indices_to_remove]
        
        return medical_data

    @staticmethod
    def _deduplicate_entries(medical_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove duplicates (including non-consecutive) across the entire report.
        Normalizes names (e.g., 'M C V' -> 'MCV') for better matching.
        """
        if not medical_data:
            return medical_data
        
        unique_entries = []
        seen_keys = set()
        
        for entry in medical_data:
            # Normalize name for the key (remove spaces/special chars)
            raw_name = entry.get("field_name", "").strip().lower()
            normalized_name = re.sub(r'[^a-zA-Z0-9]', '', raw_name)
            
            field_value = entry.get("field_value", "").strip()
            field_unit = entry.get("field_unit", "").strip().lower()
            
            # Create key from normalized name, value, AND unit
            entry_key = (normalized_name, field_value, field_unit)
            
            if entry_key not in seen_keys and raw_name:
                unique_entries.append(entry)
                seen_keys.add(entry_key)
        
        return unique_entries
    
    @staticmethod
    def standardize_field_names(medical_data: List[Dict[str, Any]], learned_synonyms: Dict[str, str] = None) -> List[Dict[str, Any]]:
        """
        Standardize field names using learned synonyms.
        Maps all variations to standard names for consistent filtering/timeline.
        
        Args:
            medical_data: List of medical data entries
            learned_synonyms: Dict mapping lowercase variations to standard names
                             E.g., {"haemoglobin": "Haemoglobin", "hemoglobin": "Haemoglobin"}
        
        Returns:
            Updated medical data with standardized field_names
        """
        
        if not learned_synonyms:
            learned_synonyms = {}
        
        for entry in medical_data:
            original_name = entry.get("field_name", "").strip()
            
            if original_name:
                # Look up standard name (case-insensitive)
                standard_name = learned_synonyms.get(original_name.lower(), original_name)
                
                # Set standard_name but PRESERVE the original name in field_name
                entry["standard_name"] = standard_name
                # We DO NOT overwrite entry["field_name"] anymore to keep original report text as written in report
        
        return medical_data
    
    @staticmethod
    def _clean_medical_entry(
        entry: Dict[str, Any],
        strict_validation: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Clean a single medical data entry.
        Returns None if entry fails validation (incomplete data).
        """
        
        field_name = str(entry.get("field_name", "")).strip().strip('[]')
        field_value = str(entry.get("field_value", "")).strip().strip('[]')
        field_unit = str(entry.get("field_unit", "")).strip().strip('[]')
        normal_range = str(entry.get("normal_range", "")).strip().strip('[]')
        category = str(entry.get("category", "")).strip().strip('[]')
        notes = str(entry.get("notes", "")).strip().strip('[]')
        
        # Clean literal "None" string in notes (VLM sometimes outputs "None" instead of empty)
        if notes.lower() == "none":
            notes = ""
        
        # Skip rows that are clearly table headers (case-insensitive regex)
        header_patterns = [
            r'^result[:\s]*$', r'^investigation[:\s]*$', r'^normal[:\s]*ranges?$', 
            r'^unit[:\s]*$', r'^field[:\s]*name$', r'^test[:\s]*name$',
            r'^الفحص', r'^النتيجة', r'^الوحدة', r'^النتيجة الطبيعية', r'^ملاحظات'
        ]
        if any(re.search(pat, field_name.lower()) for pat in header_patterns):
            return None
            
        # Sentinel Check: Discard placeholders used to maintain alignment
        sentinels = ["PHANTOM", "EMPTY_SPECIFIED", "N/A", "EMPTY", "EMPTY_IN_IMAGE"]
        if field_value.upper() in sentinels or field_value in sentinels:
            field_value = ""
            
        # Drop only if everything is missing
        if not field_name and not field_value and not field_unit and not normal_range and not category and not notes:
            return None

        # Special check: if field_value is empty, we keep it if it has a name
        # (USER REQUEST: Total Row Extraction Mode)
        if not field_value and not field_name:
            return None

        # Flag clearly malformed rows but keep them
        if MedicalDataPostProcessor._is_value_malformed(field_value, field_unit, normal_range):
            notes = MedicalDataPostProcessor._append_note(notes, "value_malformed")
            # If the value looks like a range, it's highly likely a column swap/misalignment
            if "(" in field_value and ")" in field_value and "-" in field_value:
                # In strict mode, we might want to drop these, but for now we flag them
                notes = MedicalDataPostProcessor._append_note(notes, "check_alignment")
            
        # USER REQUEST: Total Extraction Mode (preserving empty rows)
        is_val_empty = not field_value or field_value in ["-", ".", "(-)", "EMPTY"]
        if is_val_empty:
             # Preserve row for the user
             field_value = ""
        
        # Sanitize normal range if it looks malformed or wildly mismatched
        normal_range, notes = MedicalDataPostProcessor._sanitize_normal_range(
            field_name,
            field_value,
            field_unit,
            normal_range,
            notes
        )
        
        # If range sanity check detected value was grabbed from range boundary,
        # clear the value — it's not a real measurement result
        if 'value_from_range' in notes:
            field_value = ""

        # normal_range can be empty - that's OK
        # field_unit can be empty - that's OK
        # category and notes can be empty - that's OK
        
        # Fix common OCR/VLM typos in field names
        typo_fixes = {
            "Platelel": "Platelet",
            "Platelat": "Platelet",
            "Distrubtion": "Distribution",
            "disinbution": "distribution",
            "Coun": "Count",
            "Countt": "Count",
            "widt": "width",
            "widht": "width",
            "distribution widthh": "distribution width",
            "Lymphocyle": "Lymphocyte",
            "Lymphocytes9": "Lymphocytes",
            "Basohil8": "Basophils",
            "granulocs": "granulocytes",
            "Monocyle": "Monocytes",
            "Monocyles": "Monocytes",
            "Monocytess": "Monocytes",
            "(HGB": "(HGB)",
            "(RBC": "(RBC)",
            "(HC": "(HCT)",
            "(MCV": "(MCV)",
            "(MCH": "(MCH)",
            "(MCHC": "(MCHC)",
            "White blood cellsI": "White blood cells",
            "Neutrophils granuloc%": "Neutrophils granulocytes",
            "Neutrophils Granuloc": "Neutrophils Granulocytes",
            "Mean cell haemoglobin concentration (MCH)C": "Mean cell haemoglobin concentration (MCHC)",
            "Mean cell hemoglobin concentration (MCH)C)": "Mean cell haemoglobin concentration (MCHC)",
            "Mean cell hemoglobin concentration (MCH)C": "Mean cell haemoglobin concentration (MCHC)",
            "Mean cell hemoglobin concentration (MCHC)": "Mean cell haemoglobin concentration (MCHC)",
            "(MCH)C)": "(MCHC)",
            "(MCH)C": "(MCHC)",
            "Cholesterol, Tota": "Cholesterol, Total",
            "Cholesterol,Tota": "Cholesterol,Total",
            "(GPTI": "(GPT)",
            "(GOTI": "(GOT)",
            "(ALTI": "(ALT)",
            "(ASTI": "(AST)",
            "HCT)T)": "HCT)",
            "))": ")",
            "Cholesterol,Totall": "Cholesterol,Total",
            "Cholesterol, Totall": "Cholesterol, Total",
            "Monocytes(%": "Monocytes(%)",
            "Lymphocytes%": "Lymphocytes(%)",
            "Lymphocytes/": "Lymphocytes",
            "M.C.V": "MCV",
            "M.C.H": "MCH",
            "M.C.H.C": "MCHC",
            "R.B.C": "RBC",
            "W.B.C": "WBC",
            "H.G.B": "HGB",
            "H.C.T": "HCT",
            "P.L.T": "PLT",
            "(ALPI": "(ALP)",
            "(GGT": "(GGT)",
            "Neutrophils Granuloc%": "Neutrophils (%)",
            "Neutrophils granuloc%": "Neutrophils (%)",
            "Platelet Distrubtion Witdh": "PDW",
            "Platelet Distrubtion Width": "PDW",
            "Platelet Distribution Witdh": "PDW",
            "Red blood cell distribution width": "RDW",
            "Red blood cell distribution widthh": "RDW",
            "Red blood cell distribution widt": "RDW",
            "RDW coefficient of variation": "RDW-CV",
            "Red blood cell distribution width coefficient of variation": "RDW-CV",
            "Red blood cell distribution width coeficient of variation": "RDW-CV",
            "Red blood cell distribution width cocficient of variation": "RDW-CV",
            "Neutrophils granuloc": "Neutrophils Granulocytes",
            "Eosinophils(%": "Eosinophils(%)",
            "Basophils(%": "Basophils(%)",
            "Basophiles(%": "Basophiles(%)",
            "Basophiles": "Basophils",
            "Mean Platelet Volume(MPV": "Mean Platelet Volume (MPV)",
            "Mean Platelet Volume(MPV)": "Mean Platelet Volume (MPV)",
        }
        for typo, fix in typo_fixes.items():
            if typo in field_name:
                field_name = field_name.replace(typo, fix)
        
        # Strip trailing garbage characters from OCR (e.g. "Lymphocytes9", "ResultI")
        # But preserve valid endings like "(MCH)", "(HCT)", parenthesized abbreviations
        if not field_name.endswith(')'):
            field_name = re.sub(r"[I19]+$", "", field_name)
        # Fix double opening parens
        field_name = field_name.replace("((", "(").strip()

        # Remove unit from normal_range if it's already in field_unit
        # e.g., "12 - 16 g/dl" → "12 - 16" when field_unit is "g/dl"
        normal_range = MedicalDataPostProcessor._strip_unit_from_range(normal_range, field_unit)

        cleaned_entry = {
            "field_name": field_name,
            "field_value": field_value,
            "field_unit": field_unit if field_unit else "",
            "normal_range": normal_range if normal_range else "",
            "category": category if category else "",
            "notes": notes if notes else "",
            "is_normal": None  # Will be calculated later
        }
        
        return cleaned_entry
    
    @staticmethod
    def _is_value_malformed(
        field_value: str,
        field_unit: str,
        normal_range: str
    ) -> bool:
        """
        Check if a field_value looks malformed.
        
        Malformed patterns:
        - value looks like a unit (%, /uL, /dL, etc)
        - value looks like a range ((x-y), [x-y])
        - value is clearly a range
        """
        
        if not field_value:
            return False
        
        lower_value = field_value.lower()
        
        # Check if value looks like a unit
        unit_patterns = ["%", "/ul", "/dl", "/l", "k/ul", "cells/l", "g/dl", "mg/dl", 
                        "iu/l", "mm/h", "μl", "mmol/l"]
        for pattern in unit_patterns:
            if pattern in lower_value:
                return True
        
        # Check if value looks like a range
        if "(" in field_value and ")" in field_value and "-" in field_value:  # (x-y) pattern
            return True
        if "[" in field_value and "]" in field_value and "-" in field_value:  # [x-y] pattern
            return True
        if re.match(r"^\d+ - \d+$", field_value):  # x - y pattern
            return True
        
        # Check for unit leakage (e.g. value is "mg/dl")
        if re.match(r"^[a-zA-Z/]+$", field_value) and len(field_value) > 1:
            return True

        return False

    @staticmethod
    def _sanitize_normal_range(
        field_name: str,
        field_value: str,
        field_unit: str,
        normal_range: str,
        notes: str
    ) -> tuple:
        """
        Sanitize normal_range when it looks malformed or severely mismatched.
        Returns (cleaned_range, updated_notes).
        """
        if not normal_range:
            return normal_range, notes

        range_str = str(normal_range).strip()
        if not range_str:
            return "", notes

        # Validate percent-like ranges
        name_lower = str(field_name).lower()
        unit_lower = str(field_unit).lower()
        
        # If the range contains clear medical state words, it is valid even with no digits
        medical_state_keywords = ["normal", "deficient", "insufficient", "sufficient", "toxicity", "prediabetes", "diabetes", "negative", "positive", "reactive", "non-reactive"]
        if any(word in range_str.lower() for word in medical_state_keywords):
            return range_str, notes

        # If range is just a dash in parentheses like "(-)", "(—)", "(–)", or plain "-",
        # it means "no reference range" — return empty silently (not an error)
        if re.match(r'^\(?\s*[-\u2014\u2013]\s*\)?$', range_str):
            return "", notes

        has_digit = bool(re.search(r"\d", range_str))
        has_inequality = any(sym in range_str for sym in ["<", ">"])
        has_limit_word = any(word in range_str.lower() for word in ["up to", "less than", "below", "above", "more than"])

        if not has_digit and not has_inequality and not has_limit_word:
            return "", MedicalDataPostProcessor._append_note(notes, "range_invalid")

        # Extract numeric values from the range
        range_numbers = re.findall(r"[\d.]+", range_str)
        if len(range_numbers) < 1 and not has_inequality and not has_limit_word:
            return "", MedicalDataPostProcessor._append_note(notes, "range_invalid")

        # Validate percent-like ranges
        name_lower = str(field_name).lower()
        unit_lower = str(field_unit).lower()
        is_percent = "%" in unit_lower or "%" in range_str or "percent" in name_lower
        if is_percent and range_numbers:
            try:
                max_val = max(float(n) for n in range_numbers)
                min_val = min(float(n) for n in range_numbers)
                if min_val < 0 or max_val > 100:
                    return "", MedicalDataPostProcessor._append_note(notes, "range_invalid")
            except ValueError:
                return "", MedicalDataPostProcessor._append_note(notes, "range_invalid")

        # If we can parse a value and a two-sided range, sanity check for extreme mismatch
        value_match = re.search(r"[\d.]+", str(field_value))
        if value_match and len(range_numbers) >= 2:
            try:
                value_num = float(value_match.group())
                min_val = float(range_numbers[0])
                max_val = float(range_numbers[1])
                if min_val > max_val:
                    min_val, max_val = max_val, min_val

                # If value is an order of magnitude outside range, treat range as unreliable
                if value_num < (min_val * 0.1) or value_num > (max_val * 10):
                    return "", MedicalDataPostProcessor._append_note(notes, "range_unreliable")
                    
                # 1-OFF ERROR DETECTION: 
                # If value EXACTLY matches min or max, it's highly suspicious for a row-shift 
                # (extracting the range boundary as the value)
                if abs(value_num - min_val) < 1e-9 or abs(value_num - max_val) < 1e-9:
                     # Only flag if there's no flag already from VLM
                     if "*" not in str(field_value) and "#" not in str(field_value):
                        notes = MedicalDataPostProcessor._append_note(notes, "value_from_range")
            except ValueError:
                return "", MedicalDataPostProcessor._append_note(notes, "range_invalid")

        return range_str, notes

    @staticmethod
    def _strip_unit_from_range(normal_range: str, field_unit: str) -> str:
        """
        Remove the unit from normal_range when it duplicates field_unit.
        e.g., "12 - 16 g/dl" with unit "g/dl" → "12 - 16"
              "70 - 150 ug/dl" with unit "ug/dl" → "70 - 150"
              "Male: < 15, Female: < 20 mm/l" with unit "mm" → "Male: < 15, Female: < 20"
        Preserves ranges that contain medical state words (e.g., "Normal: less than 5.7 %").
        """
        if not normal_range or not field_unit:
            return normal_range
        
        unit = field_unit.strip()
        if not unit:
            return normal_range
        
        # Build list of unit variants to strip (case-insensitive)
        # e.g., for "g/dl" also try "g/dL", "G/dL", etc.
        unit_lower = unit.lower()
        
        # Strip the unit (and optional whitespace before it) from the end of each line
        lines = normal_range.split('\n')
        cleaned_lines = []
        for line in lines:
            stripped = line.rstrip()
            # Try removing the unit from the end of the line
            if stripped.lower().endswith(unit_lower):
                stripped = stripped[:len(stripped) - len(unit_lower)].rstrip()
                # Also remove trailing comma or semicolon left behind
                stripped = stripped.rstrip(',;').rstrip()
            cleaned_lines.append(stripped)
        
        return '\n'.join(cleaned_lines)

    @staticmethod
    def _append_note(existing: str, note: str) -> str:
        if not note:
            return existing
        if not existing:
            return note
        if note in existing:
            return existing
        return f"{existing}; {note}"
    
    # Phrases that indicate the VLM echoed the prompt template instead of reading the image
    PROMPT_ECHO_PATTERNS = [
        "read exact", "from image", "person name", "verified/corrected",
        "literal age", "letter by letter", "char-by-char", "absolute authority",
        "visually confirmed", "hallucination", "الطبيب", "اسم المريض",
        "not a clinic", "not a facility", "next to",
    ]

    @staticmethod
    def _is_prompt_echo(text: str) -> bool:
        """Detect if text is a VLM prompt echo (instruction text returned as value)."""
        if not text:
            return False
        lower = text.lower()
        # If it contains 2+ prompt-like phrases, it's definitely a prompt echo
        matches = sum(1 for p in MedicalDataPostProcessor.PROMPT_ECHO_PATTERNS if p in lower)
        if matches >= 2:
            return True
        # If it's very long and contains instruction-like words
        if len(text) > 60 and matches >= 1:
            return True
        return False

    @staticmethod
    def _clean_doctor_name(name: str) -> str:
        """
        Clean doctor name.
        Reject prompt echoes, facility names, and corrupted text.
        """
        if not name:
            return ""
        name = str(name).strip()
        
        # Reject empty/placeholder values
        if name.lower() in ('n/a', 'na', 'unknown', 'none', 'empty', '-', ''):
            return ""
        
        # Reject prompt echoes (VLM returned the instruction text as the value)
        if MedicalDataPostProcessor._is_prompt_echo(name):
            return ""
        
        # Reject facility/institution names
        rejection_terms = ["مختبر", "مرفق", "مستشفى", "تأمين", "وزارة", "مديرية",
                          "مستوصف", "رعاية", "شؤون", "شذون", "اجتماعية",
                          "عيادة", "عباده", "عياده", "العام", "صحة", "صحه",
                          "مديربه", "مديريه", "رام الله", "جهة الطلب",
                          "الطب العام", "الصحة", "مركز",
                          "clinic", "hospital", "lab", "laboratory",
                          "ministry", "directorate", "insurance",
                          "phc", "center", "centre", "health"]
        name_lower = name.lower()
        for term in rejection_terms:
            if term in name_lower:
                return ""
        
        # Remove titles
        titles = ["dr.", "dr", "prof.", "prof", "د.", "دكتور", "أ.د", "الدكتور",
                 "أستاذ", "البروفيسور"]
        for title in titles:
            if name_lower.startswith(title):
                name = name[len(title):].strip()
                name_lower = name.lower()
        
        if len(name) < 2:
            return ""
        
        return MedicalDataPostProcessor._normalize_arabic_text(name)

    @staticmethod
    def _clean_patient_name(name: str) -> str:
        """
        Clean patient name.
        Remove titles and position words.
        Reject corrupted/nonsensical text.
        """
        if not name:
            return ""
        
        name = str(name).strip()
        
        # Indicators of corruption: random symbols, facility words, insurance terms
        # Reject prompt echoes (VLM returned the instruction text as the value)
        if MedicalDataPostProcessor._is_prompt_echo(name):
            return ""
        
        corruption_indicators = ["مختبر", "مرفق", "مستشفى", "تأمين", "وزارة", "مديرية", "مستوصف", "رعاية", "شؤون", "شذون", "اجتماعية"]
        for indicator in corruption_indicators:
            if indicator in name:
                # Likely a facility/insurance not a person
                return ""
        
        # Remove common titles
        titles = ["dr.", "dr", "prof.", "prof", "د.", "دكتور", "أ.د", "الدكتور", 
                 "أستاذ", "البروفيسور", "mr.", "mr", "mrs.", "mrs", "ms.", "ms"]
        
        name_lower = name.lower()
        for title in titles:
            if name_lower.startswith(title):
                name = name[len(title):].strip()
                name_lower = name.lower()
        
        # Must be at least 3 characters and look like a name (not a facility)
        if len(name) < 3:
            return ""
        
        # Exclude facility names
        facilities = ["clinic", "hospital", "lab", "laboratory", "phc", "center", "centre", 
                     "مختبر", "مرفق", "مستشفى", "عيادة", "جهاز", "دارة", "وزارة", "مديرية", "مستوصف", "رعاية"]
        
        if any(facility in name_lower for facility in facilities):
            return ""
        
        # Check if name contains meaningful Arabic or English words
        # If mostly gibberish, reject it
        words = name.split()
        if len(words) == 0:
            return ""
        
        # Reject if contains too many unusual characters or patterns
        # Corrupted text often has garbled Unicode or unusual patterns
        has_corruption = False
        for word in words:
            # Check for patterns like "خـير" (corrupted text)
            if "ـ" in word and len(word) < 3:  # Short words with diacritics
                has_corruption = True
            # Check for words that are just punctuation
            if not any(c.isalnum() for c in word):
                has_corruption = True
        
        if has_corruption and len(words) <= 2:
            return ""
        
        # Normalize Arabic text: remove tatweel, fix disjointed characters
        name = MedicalDataPostProcessor._normalize_arabic_text(name)
            
        return name

    @staticmethod
    def _normalize_arabic_text(text: str) -> str:
        """
        Remove Arabic Tatweel (Kashida), normalize confusable characters,
        and fix disjointed character patterns.
        e.g. "أحمد نعی رات" -> "أحمد نعيرات"
        """
        if not text:
            return ""
        
        # 1. Remove Tatweel (U+0640)
        text = text.replace("\u0640", "")
        
        # 2. Remove diacritics (tashkeel) that cause inconsistent matching
        import unicodedata
        diacritics = [
            '\u064B', '\u064C', '\u064D', '\u064E', '\u064F',
            '\u0650', '\u0651', '\u0652', '\u0670',
        ]
        for d in diacritics:
            text = text.replace(d, '')
        
        # 3. Normalize confusable Arabic characters (reduces OCR variation)
        arabic_normalizations = {
            'ی': 'ي',   # Persian Yi → Arabic Ya
            'ک': 'ك',   # Persian Keh → Arabic Kaf
            'ۀ': 'ه',   # Heh with Yeh above → Heh
            'ە': 'ه',   # AE Heh → Heh
            'ٱ': 'ا',   # Alef Wasla → Alef
            'إ': 'ا',   # Alef with Hamza below → Alef
            'أ': 'ا',   # Alef with Hamza above → Alef
            'آ': 'ا',   # Alef with Madda → Alef
            'ؤ': 'و',   # Waw with Hamza → Waw
            'ئ': 'ي',   # Yeh with Hamza → Yeh
            'ة': 'ه',   # Teh Marbuta → Heh (for matching, not display)
        }
        for src, dst in arabic_normalizations.items():
            text = text.replace(src, dst)
        
        # 4. Fix common disjointed patterns (single space between Arabic letters)
        words = text.split()
        if len([w for w in words if len(w) == 1]) > len(words) / 3:
            # High density of single letters - aggressive rejoin
            text = "".join(words)
        
        return text.strip()
    
    @staticmethod
    def _clean_age(age: str, report_date: str = "") -> str:
        """
        Clean and validate age.
        If age is a date (DOB), calculate age from report_date.
        
        Args:
            age: Age or DOB string
            report_date: Report date to use for DOB calculation (YYYY-MM-DD format)
        
        Returns:
            Age as a number string
        """
        if not age:
            return ""
        
        age_str = str(age).strip()
        
        # Check if age contains date separators (/ or -)
        if '/' in age_str or '-' in age_str:
            # This looks like a date (DOB), try to calculate age
            calculated_age = MedicalDataPostProcessor._calculate_age_from_dob(age_str, report_date)
            if calculated_age:
                return str(calculated_age)
        
        # First try to extract numeric age
        numeric_age = ''.join(c for c in age_str if c.isdigit())
        
        # If we have a 4-digit number that looks like a year, it might be a DOB
        if len(numeric_age) == 4:
            # Could be a year (DOB)
            try:
                year = int(numeric_age)
                if 1900 <= year <= 2100:
                    # Try to parse as DOB and calculate age
                    calculated_age = MedicalDataPostProcessor._calculate_age_from_dob(age_str, report_date)
                    if calculated_age:
                        return str(calculated_age)
            except:
                pass
        
        # If we have 6 or 8 digits, likely a DOB (DDMMYYYY or YYYYMMDD)
        if len(numeric_age) in [6, 8]:
            calculated_age = MedicalDataPostProcessor._calculate_age_from_dob(age_str, report_date)
            if calculated_age:
                return str(calculated_age)
        
        # Try regular numeric age
        if numeric_age and len(numeric_age) <= 3:
            try:
                age_num = int(numeric_age)
                # Validate age is within reasonable bounds (1-150)
                if 1 <= age_num <= 150:
                    return numeric_age
            except:
                pass
        
        return ""
    
    @staticmethod
    def _calculate_age_from_dob(dob_str: str, report_date_str: str = "") -> Optional[int]:
        """
        Calculate age from Date of Birth and report date.
        
        Args:
            dob_str: Date of birth string (various formats)
            report_date_str: Report date in YYYY-MM-DD format
        
        Returns:
            Calculated age in years, or None if cannot calculate
        """
        try:
            from datetime import datetime
            import re
            
            # Parse DOB
            dob_patterns = [
                (r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', 'ymd'),  # YYYY-MM-DD
                (r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', 'dmy'),  # DD-MM-YYYY
            ]
            
            dob_date = None
            for pattern, format_type in dob_patterns:
                match = re.search(pattern, dob_str)
                if match:
                    if format_type == 'ymd':
                        year, month, day = match.groups()
                    else:  # dmy
                        day, month, year = match.groups()
                    
                    try:
                        dob_date = datetime(int(year), int(month), int(day))
                        break
                    except:
                        pass
            
            if not dob_date:
                return None
            
            # Parse report date
            report_date = None
            if report_date_str:
                try:
                    report_date = datetime.strptime(report_date_str, "%Y-%m-%d")
                except:
                    pass
            
            # Use current date if no report date
            if not report_date:
                report_date = datetime.now()
            
            # Calculate age
            age = report_date.year - dob_date.year
            
            # Adjust if birthday hasn't occurred yet this year
            if (report_date.month, report_date.day) < (dob_date.month, dob_date.day):
                age -= 1
            
            # Validate age is reasonable
            if 0 <= age <= 150:
                return age
            
            return None
        except:
            return None
    
    
    @staticmethod
    def _clean_gender(gender: str) -> str:
        """Clean and normalize gender to Male/Female."""
        if not gender:
            return ""
        
        gender_str = str(gender).strip().lower()
        
        # Male variations
        if gender_str in ['male', 'm', 'ذكر', 'ذكر ', ' ذكر']:
            return 'Male'
        
        # Female variations
        elif gender_str in ['female', 'f', 'أنثى', 'انثى', 'أنثي', 'انثي']:
            return 'Female'
        
        # Already normalized
        elif gender_str in ['male', 'female']:
            return gender_str.capitalize()
        
        return ""
    
    @staticmethod
    def _clean_date(date_str: str) -> str:
        """Clean and normalize date to YYYY-MM-DD format."""
        if not date_str:
            return ""
        
        date_str = str(date_str).strip()
        
        # Strip timestamp suffix (e.g. "2025-12-31 10:00:02.0" → "2025-12-31")
        import re
        ts_match = re.match(r'(\d{4}-\d{2}-\d{2})\s+\d', date_str)
        if ts_match:
            date_str = ts_match.group(1)
        
        # If already in YYYY-MM-DD format, return it
        if len(date_str) == 10 and date_str[4] == '-' and date_str[7] == '-':
            return date_str
        
        # Try to extract date components
        import re
        
        # Pattern: DD/MM/YYYY or DD-MM-YYYY or YYYY-MM-DD
        patterns = [
            (r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', 'ymd'),  # YYYY-MM-DD
            (r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', 'dmy'),  # DD-MM-YYYY
        ]
        
        for pattern, format_type in patterns:
            match = re.search(pattern, date_str)
            if match:
                if format_type == 'ymd':
                    year, month, day = match.groups()
                else:  # dmy
                    day, month, year = match.groups()
                
                # Validate
                try:
                    year = int(year)
                    month = int(month)
                    day = int(day)
                    
                    if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                        return f"{year:04d}-{month:02d}-{day:02d}"
                except:
                    pass
        
        return ""
    
    @staticmethod
    def calculate_is_normal(
        field_value: str,
        normal_range: str,
        field_unit: str = "",
        patient_gender: str = ""
    ) -> Optional[bool]:
        """
        Calculate if a value is within normal range (delegates to MedicalValidator).
        """
        from utils.medical_validator import MedicalValidator
        return MedicalValidator.calculate_is_normal(field_value, normal_range, patient_gender=patient_gender)
    
    @staticmethod
    def add_is_normal_to_entries(medical_data: List[Dict[str, Any]], patient_gender: str = "") -> List[Dict[str, Any]]:
        """Calculate is_normal for all entries."""
        
        for entry in medical_data:
            entry['is_normal'] = MedicalDataPostProcessor.calculate_is_normal(
                entry.get('field_value', ''),
                entry.get('normal_range', ''),
                entry.get('field_unit', ''),
                patient_gender=patient_gender
            )
        
        return medical_data
    
    @staticmethod
    def validate_extraction_quality(
        extracted_data: Dict[str, Any],
        minimum_fields: int = 5
    ) -> Dict[str, Any]:
        """
        Validate overall extraction quality.
        
        Returns:
            Quality report with issues and recommendations
        """
        
        quality_report = {
            "total_fields_extracted": len(extracted_data.get("medical_data", [])),
            "has_patient_name": bool(extracted_data.get("patient_name")),
            "has_report_date": bool(extracted_data.get("report_date")),
            "has_doctor_info": bool(extracted_data.get("doctor_names")),
            "meets_minimum_threshold": len(extracted_data.get("medical_data", [])) >= minimum_fields,
            "issues": [],
            "warnings": []
        }
        
        # Check for issues
        if not quality_report["has_patient_name"]:
            quality_report["issues"].append("Missing patient name")
        
        if not quality_report["has_report_date"]:
            quality_report["issues"].append("Missing report date")
        
        if not quality_report["meets_minimum_threshold"]:
            quality_report["issues"].append(
                f"Only {quality_report['total_fields_extracted']} fields extracted "
                f"(minimum: {minimum_fields})"
            )
        
        # Check for warnings
        if not quality_report["has_doctor_info"]:
            quality_report["warnings"].append("Doctor information not found")
        
        # Check for missing ranges
        entries_without_ranges = sum(
            1 for entry in extracted_data.get("medical_data", [])
            if not entry.get("normal_range")
        )
        
        if entries_without_ranges > 0:
            quality_report["warnings"].append(
                f"{entries_without_ranges} fields missing normal ranges (OK per requirements)"
            )
        
        return quality_report
