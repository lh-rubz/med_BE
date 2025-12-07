from models import db, MedicalSynonym

# Initial static list for seeding
INITIAL_ALIASES = {
    # Complete Blood Count (CBC)
    'hemoglobin': ['hemoglobin', 'haemoglobin', 'hgb', 'hb'],
    'wbc': ['wbc', 'white blood cell', 'white blood count', 'leukocytes', 'tlc'],
    'rbc': ['rbc', 'red blood cell', 'red blood count', 'erythrocytes'],
    'platelets': ['platelet', 'plt', 'thrombocyte', 'platelet count'],
    'hematocrit': ['hematocrit', 'hct', 'pcv', 'packed cell volume'],
    'mcv': ['mcv', 'mean corpuscular volume'],
    'mch': ['mch', 'mean corpuscular hemoglobin'],
    'mchc': ['mchc', 'mean corpuscular hemoglobin concentration'],
    
    # Blood Sugar / Diabetes
    'glucose': ['glucose', 'sugar', 'bsl', 'fbs', 'rbs', 'ppbs'],
    'hba1c': ['hba1c', 'a1c', 'glycated hemoglobin', 'glycosylated hemoglobin'],
    'insulin': ['insulin', 'fasting insulin'],
    
    # Lipid Profile
    'cholesterol': ['cholesterol', 'total cholesterol'],
    'hdl': ['hdl', 'high density', 'good cholesterol'],
    'ldl': ['ldl', 'low density', 'bad cholesterol'],
    'triglycerides': ['triglycerides', 'tg'],
    
    # Liver Function
    'sgot': ['sgot', 'ast', 'aspartate aminotransferase'],
    'sgpt': ['sgpt', 'alt', 'alanine aminotransferase'],
    'bilirubin': ['bilirubin', 'bili'],
    'alkaline phosphatase': ['alkaline phosphatase', 'alp', 'sap'],
    
    # Kidney Function
    'creatinine': ['creatinine', 'creat', 's.creat'],
    'urea': ['urea', 'blood urea', 'bun'],
    'uric acid': ['uric acid'],
    
    # Thyroid
    'tsh': ['tsh', 'thyroid stimulating hormone'],
    't3': ['t3', 'triiodothyronine'],
    't4': ['t4', 'thyroxine'],
    
    # Vitamins
    'vitamin d': ['vitamin d', 'vit d', '25-oh'],
    'vitamin b12': ['vitamin b12', 'vit b12', 'cobalamin'],
    
    # Electrolytes
    'sodium': ['sodium', 'na', 'na+'],
    'potassium': ['potassium', 'k', 'k+'],
    'calcium': ['calcium', 'ca', 'ca++'],
    'chloride': ['chloride', 'cl', 'cl-']
}

def seed_synonyms():
    """Populate database with initial aliases if empty"""
    try:
        # Check if we have any data
        if MedicalSynonym.query.first():
            return
            
        print("🌱 Seeding medical synonyms...")
        count = 0
        for standard, aliases in INITIAL_ALIASES.items():
            for alias in aliases:
                # Check existence to be safe
                if not MedicalSynonym.query.filter_by(synonym=alias.lower()).first():
                    db.session.add(MedicalSynonym(
                        standard_name=standard.lower(),
                        synonym=alias.lower()
                    ))
                    count += 1
        
        db.session.commit()
        print(f"✅ Added {count} synonyms to database")
    except Exception as e:
        print(f"⚠️ Initial seed failed (tables might not exist yet): {e}")

def get_search_terms(query):
    """
    Expand a search query into a list of synonyms/aliases from DATABASE.
    """
    query_lower = query.lower().strip()
    terms = {query_lower}
    
    try:
        # 1. Try to find if query is a synonym or standard name
        # Find the standard name for this query
        match = MedicalSynonym.query.filter_by(synonym=query_lower).first()
        
        if match:
            standard = match.standard_name
        else:
            # Maybe it IS the standard name?
            is_standard = MedicalSynonym.query.filter_by(standard_name=query_lower).first()
            standard = query_lower if is_standard else None
            
        if standard:
            # 2. Get ALL synonyms for this standard name
            aliases = MedicalSynonym.query.filter_by(standard_name=standard).all()
            for alias in aliases:
                terms.add(alias.synonym)
            terms.add(standard)
            
    except Exception as e:
        print(f"⚠️ DB Loookup failed: {e}")
        # Fallback to static in memory if DB fails
        for std, aliases in INITIAL_ALIASES.items():
            if query_lower == std or query_lower in aliases:
                terms.update(aliases)
                terms.add(std)
                
    return list(terms)

def add_new_alias(synonym, standard_name):
    """Add a new alias to the database"""
    try:
        synonym = synonym.lower().strip()
        standard_name = standard_name.lower().strip()
        
        if not MedicalSynonym.query.filter_by(synonym=synonym).first():
            db.session.add(MedicalSynonym(standard_name=standard_name, synonym=synonym))
            db.session.commit()
            return True
    except Exception as e:
        print(f"Failed to add alias: {e}")
        db.session.rollback()
    return False
