
from app import app
from models import db, ReportField, MedicalSynonym
from utils.medical_mappings import seed_synonyms
from utils.medical_data_postprocessor import MedicalDataPostProcessor

def backfill():
    with app.app_context():
        print("🚀 Seeding new synonyms first...")
        # Since we updated INITIAL_ALIASES, we might need to seed again
        # seed_synonyms only adds if MedicalSynonym is empty, so we might need a more robust seed
        from utils.medical_mappings import INITIAL_ALIASES
        added_count = 0
        for standard, aliases in INITIAL_ALIASES.items():
            for alias in aliases:
                alias = alias.lower().strip()
                if not MedicalSynonym.query.filter_by(synonym=alias).first():
                    db.session.add(MedicalSynonym(standard_name=standard.lower(), synonym=alias))
                    added_count += 1
        db.session.commit()
        print(f"✅ Seeded {added_count} new synonyms.")

        print("\n🚀 Starting backfill of standard_names for existing ReportFields...")
        
        # 1. Fetch all synonyms
        synonyms = MedicalSynonym.query.all()
        mapping = {s.synonym.lower().strip(): s.standard_name for s in synonyms}
        print(f"📊 Loaded {len(mapping)} synonyms total.")
        
        # 2. Fetch all ReportFields with empty standard_names (or those that might need updating)
        fields_to_fix = ReportField.query.all()
        
        print(f"📝 Checking {len(fields_to_fix)} fields for standardization...")
        
        update_count = 0
        for field in fields_to_fix:
            original_name = field.field_name.strip()
            if original_name:
                standard_name = mapping.get(original_name.lower(), original_name)
                if field.standard_name != standard_name:
                    field.standard_name = standard_name
                    update_count += 1
        
        db.session.commit()
        print(f"✅ Backfill complete. Updated {update_count} fields.")

if __name__ == "__main__":
    backfill()
