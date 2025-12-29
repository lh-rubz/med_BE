from app import app
from models import db, User, Profile

def create_self_profiles():
    with app.app_context():
        users = User.query.all()
        print(f"Found {len(users)} users. Checking for 'Self' profiles...")
        
        created_count = 0
        for user in users:
            # Check if Self profile exists
            self_profile = Profile.query.filter_by(
                creator_id=user.id,
                relationship='Self'
            ).first()
            
            if not self_profile:
                print(f"Creating 'Self' profile for user: {user.email}")
                new_profile = Profile(
                    creator_id=user.id,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    date_of_birth=user.date_of_birth,
                    gender=user.gender if hasattr(user, 'gender') and user.gender else 'Other',
                    relationship='Self'
                )
                db.session.add(new_profile)
                created_count += 1
        
        if created_count > 0:
            db.session.commit()
            print(f"✅ Successfully created {created_count} missing 'Self' profiles.")
        else:
            print("✅ All users already have a 'Self' profile.")

if __name__ == "__main__":
    create_self_profiles()
