from app import app
from models import db, User, Report, Profile
from datetime import datetime, timezone

def migrate():
    with app.app_context():
        print("🚀 Starting Family Profiles Migration...")
        
        # 1. Create tables if they don't exist
        db.create_all()
        print("✅ Database tables verified.")
        
        # 2. Create 'Self' profiles for all users who don't have one
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
        print(f"✅ Created {profiles_created} 'Self' profiles.")
        
        # 3. Link existing reports to 'Self' profiles
        reports = Report.query.filter(Report.profile_id == None).all()
        reports_linked = 0
        for report in reports:
            # Find the 'Self' profile for this user
            self_profile = Profile.query.filter_by(creator_id=report.user_id, relationship='Self').first()
            if self_profile:
                report.profile_id = self_profile.id
                reports_linked += 1
        
        db.session.commit()
        print(f"✅ Linked {reports_linked} reports to their respective 'Self' profiles.")
        print("🎉 Migration completed successfully!")

if __name__ == "__main__":
    migrate()
