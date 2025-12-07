"""
Database Migration Script: Create ReportFile Table

This script creates the report_file table to track uploaded files associated with reports.
Run this script to update your database schema.

IMPORTANT: Make sure your Flask app is running or has been run at least once
so that all other tables are created. This script will only create the ReportFile table.
"""

import sys
import os

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def create_report_file_table():
    """Create the ReportFile table in the database"""
    try:
        from app import app, db
        
        with app.app_context():
            print("Creating ReportFile table...")
            
            # Create only the new table
            from models import ReportFile
            db.create_all()
            
            print("✅ ReportFile table created successfully!")
            print("\nTable structure:")
            print("- id: Primary key")
            print("- report_id: Foreign key to Report")
            print("- user_id: Foreign key to User")
            print("- original_filename: Original uploaded filename")
            print("- stored_filename: Timestamped filename on disk")
            print("- file_path: Full path to file")
            print("- file_type: File extension")
            print("- file_size: Size in bytes")
            print("- page_number: Page number for PDF pages (null for images)")
            print("- created_at: Timestamp")
            print("\n✅ Migration complete!")
            
    except Exception as e:
        print(f"❌ Error creating table: {e}")
        print("\nIf you see import errors, make sure:")
        print("1. Your virtual environment is activated")
        print("2. All dependencies are installed (pip install -r requirements.txt)")
        print("3. Your Flask app runs without errors")
        sys.exit(1)

if __name__ == '__main__':
    create_report_file_table()
