
from app import app, db
from models import Profile

def cleanup_duplicate_self_profiles():
    with app.app_context():
        print("Starting cleanup of duplicate 'Self' profiles...")
        
        # Get all users who have created profiles
        # We can just iterate over all profiles where relationship is 'Self'
        self_profiles = Profile.query.filter_by(relationship='Self').order_by(Profile.creator_id, Profile.created_at).all()
        
        profiles_by_user = {}
        for profile in self_profiles:
            if profile.creator_id not in profiles_by_user:
                profiles_by_user[profile.creator_id] = []
            profiles_by_user[profile.creator_id].append(profile)
            
        count_updated = 0
        
        for user_id, profiles in profiles_by_user.items():
            if len(profiles) > 1:
                print(f"User {user_id} has {len(profiles)} 'Self' profiles. Fixing...")
                
                # Keep the first one (oldest due to order_by created_at)
                # profiles[0] is kept as 'Self'
                
                # Update the rest
                for duplicate in profiles[1:]:
                    print(f"  - Updating Profile ID {duplicate.id} ({duplicate.first_name}) from 'Self' to 'Family Member'")
                    duplicate.relationship = 'Family Member'
                    count_updated += 1
        
        if count_updated > 0:
            db.session.commit()
            print(f"Successfully updated {count_updated} duplicate profiles.")
        else:
            print("No duplicate 'Self' profiles found.")

if __name__ == "__main__":
    cleanup_duplicate_self_profiles()
