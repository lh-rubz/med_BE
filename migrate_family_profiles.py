"""
Database Migration Script: Add Family Profiles Support
This script adds the necessary columns and tables for family profiles feature:
1. Creates Profile table
2. Creates FamilyConnection table
3. Adds profile_id column to Report table
"""

from models import db
from app import app
from sqlalchemy import text

def migrate_family_profiles():
    """Migrate database for family profiles support"""
    with app.app_context():
        try:
            print("🚀 Starting Family Profiles Migration...")
            
            # 1. Create Profile table
            try:
                db.session.execute(text('''
                    CREATE TABLE IF NOT EXISTS profile (
                        id SERIAL PRIMARY KEY,
                        creator_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
                        linked_user_id INTEGER REFERENCES "user"(id) ON DELETE SET NULL,
                        first_name VARCHAR(50) NOT NULL,
                        last_name VARCHAR(50),
                        date_of_birth DATE,
                        gender VARCHAR(20),
                        relationship VARCHAR(50) DEFAULT 'Self',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                '''))
                db.session.commit()
                print("✅ Created Profile table")
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e):
                    print("ℹ️  Profile table already exists")
                else:
                    print(f"⚠️  Error creating Profile table: {e}")
            
            # 2. Create FamilyConnection table
            try:
                db.session.execute(text('''
                    CREATE TABLE IF NOT EXISTS family_connection (
                        id SERIAL PRIMARY KEY,
                        requester_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
                        receiver_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
                        relationship VARCHAR(50) NOT NULL,
                        status VARCHAR(20) DEFAULT 'pending',
                        access_level VARCHAR(20) DEFAULT 'view',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP
                    );
                '''))
                db.session.commit()
                print("✅ Created FamilyConnection table")
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e):
                    print("ℹ️  FamilyConnection table already exists")
                else:
                    print(f"⚠️  Error creating FamilyConnection table: {e}")
            
            # 3. Add profile_id column to Report table
            try:
                db.session.execute(text('''
                    ALTER TABLE report ADD COLUMN profile_id INTEGER REFERENCES profile(id) ON DELETE SET NULL;
                '''))
                db.session.commit()
                print("✅ Added profile_id column to Report table")
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e) or 'column "profile_id" of relation "report" already exists' in str(e):
                    print("ℹ️  profile_id column already exists in Report table")
                else:
                    print(f"⚠️  Error adding profile_id column: {e}")
            
            # 4. Create "Self" profiles for all existing users
            try:
                from models import User, Profile
                users = User.query.all()
                profiles_created = 0
                
                for user in users:
                    # Check if user already has a 'Self' profile
                    self_profile = Profile.query.filter_by(creator_id=user.id, relationship='Self').first()
                    if not self_profile:
                        self_profile = Profile(
                            creator_id=user.id,
                            first_name=user.first_name,
                            last_name=user.last_name,
                            date_of_birth=user.date_of_birth,
                            gender=user.gender,
                            relationship='Self'
                        )
                        db.session.add(self_profile)
                        profiles_created += 1
                
                db.session.commit()
                print(f"✅ Created {profiles_created} 'Self' profiles for existing users")
            except Exception as e:
                db.session.rollback()
                print(f"⚠️  Error creating Self profiles: {e}")
            
            # 5. Link existing reports to 'Self' profiles
            try:
                from models import Report, Profile
                reports = Report.query.filter(Report.profile_id == None).all()
                reports_linked = 0
                
                for report in reports:
                    # Find the 'Self' profile for this user
                    self_profile = Profile.query.filter_by(creator_id=report.user_id, relationship='Self').first()
                    if self_profile:
                        report.profile_id = self_profile.id
                        reports_linked += 1
                
                db.session.commit()
                print(f"✅ Linked {reports_linked} existing reports to 'Self' profiles")
            except Exception as e:
                db.session.rollback()
                print(f"⚠️  Error linking reports: {e}")
            
            print("\n🎉 Migration completed successfully!")
            print("\nNext steps:")
            print("1. Restart your Flask application")
            print("2. Test the new /profiles and /connections endpoints")
            print("3. Try uploading a report with profile_id parameter")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            import traceback
            traceback.print_exc()
            print("\n⚠️  If you see errors, you may need to run these SQL commands manually:")
            print("\nManual SQL commands:")
            print("-- Create Profile table")
            print('''CREATE TABLE profile (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    linked_user_id INTEGER REFERENCES "user"(id) ON DELETE SET NULL,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50),
    date_of_birth DATE,
    gender VARCHAR(20),
    relationship VARCHAR(50) DEFAULT 'Self',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);''')
            print("\n-- Create FamilyConnection table")
            print('''CREATE TABLE family_connection (
    id SERIAL PRIMARY KEY,
    requester_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    receiver_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    relationship VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    access_level VARCHAR(20) DEFAULT 'view',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);''')
            print("\n-- Add profile_id to Report table")
            print('ALTER TABLE report ADD COLUMN profile_id INTEGER REFERENCES profile(id) ON DELETE SET NULL;')

if __name__ == '__main__':
    print("=" * 80)
    print("FAMILY PROFILES DATABASE MIGRATION")
    print("=" * 80)
    migrate_family_profiles()
