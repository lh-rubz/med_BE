from app import app, db
from sqlalchemy import text

def update_database():
    with app.app_context():
        try:
            # Add two_factor_enabled column
            try:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN two_factor_enabled BOOLEAN DEFAULT FALSE'))
                print("Added two_factor_enabled column")
            except Exception as e:
                print(f"two_factor_enabled column might already exist: {e}")
                db.session.rollback()

            # Add two_factor_code column
            try:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN two_factor_code VARCHAR(255)'))
                print("Added two_factor_code column")
            except Exception as e:
                print(f"two_factor_code column might already exist: {e}")
                db.session.rollback()

            # Add two_factor_code_expires column
            try:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN two_factor_code_expires TIMESTAMP'))
                print("Added two_factor_code_expires column")
            except Exception as e:
                print(f"two_factor_code_expires column might already exist: {e}")
                db.session.rollback()

            db.session.commit()
            print("Database update completed successfully!")
        except Exception as e:
            print(f"An error occurred: {e}")
            db.session.rollback()

if __name__ == "__main__":
    update_database()
