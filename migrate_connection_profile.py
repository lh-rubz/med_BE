from models import db
from app import app
from sqlalchemy import text

def migrate_connection_profile():
    with app.app_context():
        print("Starting migration for FamilyConnection profile_id...")
        try:
            # Check if column exists first to avoid errors if run multiple times
            check_sql = text("SELECT column_name FROM information_schema.columns WHERE table_name='family_connection' AND column_name='profile_id';")
            result = db.session.execute(check_sql).fetchone()
            
            if not result:
                print("Adding profile_id column to family_connection table...")
                # Add column with foreign key constraint
                db.session.execute(text("ALTER TABLE family_connection ADD COLUMN profile_id INTEGER REFERENCES profile(id);"))
                db.session.commit()
                print("✅ Successfully added profile_id column.")
            else:
                print("ℹ️ Column profile_id already exists.")
                
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error during migration: {str(e)}")

if __name__ == "__main__":
    migrate_connection_profile()
