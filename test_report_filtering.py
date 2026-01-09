
import unittest
import json
from datetime import datetime
from flask import Flask
from flask_restx import Api
from flask_jwt_extended import JWTManager, create_access_token
from models import db, User, Profile, Report
from routes.report_routes import reports_ns
from unittest.mock import patch

class TestReportFiltering(unittest.TestCase):
    def setUp(self):
        # Create a fresh Flask application
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['TESTING'] = True
        self.app.config['JWT_SECRET_KEY'] = 'test-secret'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        
        # Initialize extensions with the testing app
        db.init_app(self.app)
        JWTManager(self.app)
        
        # Setup API and Namespaces
        self.api = Api(self.app)
        self.api.add_namespace(reports_ns)
        
        # Create Test Client
        self.client = self.app.test_client()
        
        # Push Application Context
        self.ctx = self.app.app_context()
        self.ctx.push()
        
        # Create Database and Tables (In-Memory SQLite)
        db.create_all()
        
        # Create User
        self.user = User(email='test@example.com', first_name='Test', last_name='User', password='hash')
        db.session.add(self.user)
        db.session.commit()
        self.user_id = self.user.id
        self.access_token = create_access_token(identity=str(self.user.id))

        # Create Profiles
        # Profile 1: Self
        self.profile1 = Profile(creator_id=self.user.id, first_name='Test', last_name='User', relationship='Self')
        db.session.add(self.profile1)
        
        # Profile 2: Child
        self.profile2 = Profile(creator_id=self.user.id, first_name='Baby', last_name='User', relationship='Son')
        db.session.add(self.profile2)
        db.session.commit()
        
        # Create Reports
        # Report 1 -> Profile 1
        report1 = Report(
            user_id=self.user.id, 
            profile_id=self.profile1.id, 
            report_date=datetime.now(),
            report_hash='abc',
            patient_name='Test User'
        )
        db.session.add(report1)

        # Report 2 -> Profile 2
        report2 = Report(
            user_id=self.user.id, 
            profile_id=self.profile2.id, 
            report_date=datetime.now(),
            report_hash='def',
            patient_name='Baby User'
        )
        db.session.add(report2)
        db.session.commit()

        self.report1_id = report1.id
        self.report2_id = report2.id

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    @patch('utils.access_verification.check_access_permission')
    def test_filter_by_profile_success(self, mock_check):
        """Test that filtering by profile_ID returns ONLY reports for that profile"""
        # Mock access permission to allow access without verification
        mock_check.return_value = (True, False, None)
        
        headers = {'Authorization': f'Bearer {self.access_token}'}
        
        # Request Profile 1
        response = self.client.get(f'/reports?profile_id={self.profile1.id}', headers=headers)
        data = json.loads(response.data)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data['reports']), 1)
        self.assertEqual(data['reports'][0]['profile_id'], self.profile1.id)
        self.assertEqual(data['reports'][0]['patient_name'], 'Test User')
        
        # Check that we did NOT get Report 2
        report_ids = [r['report_id'] for r in data['reports']]
        self.assertIn(self.report1_id, report_ids)
        self.assertNotIn(self.report2_id, report_ids)

    @patch('utils.access_verification.check_access_permission')
    def test_filter_by_profile2_success(self, mock_check):
        """Test that filtering by profile 2 returns ONLY reports for profile 2"""
        # Mock access permission to allow access without verification
        mock_check.return_value = (True, False, None)
        
        headers = {'Authorization': f'Bearer {self.access_token}'}
        
        # Request Profile 2
        response = self.client.get(f'/reports?profile_id={self.profile2.id}', headers=headers)
        data = json.loads(response.data)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data['reports']), 1)
        self.assertEqual(data['reports'][0]['profile_id'], self.profile2.id)
        self.assertEqual(data['reports'][0]['patient_name'], 'Baby User')

    def test_unauthorized_profile_access(self):
        """Test accessing a profile ID that does not belong to user"""
        headers = {'Authorization': f'Bearer {self.access_token}'}
        
        # Random ID
        response = self.client.get('/reports?profile_id=999', headers=headers)
        
        self.assertEqual(response.status_code, 403)
        data = json.loads(response.data)
        self.assertIn('message', data)

    @patch('utils.access_verification.check_access_permission')
    def test_response_fields(self, mock_check):
        """Ensure ensure reports always include profile_id and patient_name"""
        # Mock access permission
        mock_check.return_value = (True, False, None)

        headers = {'Authorization': f'Bearer {self.access_token}'}
        response = self.client.get(f'/reports?profile_id={self.profile1.id}', headers=headers)
        data = json.loads(response.data)
        
        report = data['reports'][0]
        self.assertIn('profile_id', report)
        self.assertIn('patient_name', report)
        self.assertIsNotNone(report['patient_name'])

if __name__ == '__main__':
    unittest.main()
