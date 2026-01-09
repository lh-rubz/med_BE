import unittest
from unittest.mock import patch
from app import app
from models import db, User
import json
from datetime import datetime, timezone, timedelta
import uuid

class Test2FAFix(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = app.test_client()
        self.test_email = f'test_{uuid.uuid4()}@example.com'
        
        with app.app_context():
            print(f"DEBUG: DB URI is {app.config['SQLALCHEMY_DATABASE_URI']}")
            db.create_all()
            # Create a test user
            user = User(
                email=self.test_email,
                first_name='Test',
                email_verified=True
            )
            user.set_password('password123')
            db.session.add(user)
            db.session.commit()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def get_token(self):
        response = self.client.post('/auth/login', json={
            'email': self.test_email,
            'password': 'password123'
        })
        return json.loads(response.data)['access_token']

    @patch('routes.auth_routes.send_brevo_email')
    def test_2fa_rate_limiting(self, mock_email):
        mock_email.return_value = True
        token = self.get_token()
        headers = {'Authorization': f'Bearer {token}'}

        # 1. Enable 2FA (First request) - Should succeed
        response = self.client.post('/auth/2fa/enable', headers=headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['expires_in_minutes'], 10)

        # 2. Enable 2FA (Second request immediately) - Should fail with 429
        response = self.client.post('/auth/2fa/enable', headers=headers)
        self.assertEqual(response.status_code, 429)
        data = json.loads(response.data)
        self.assertIn('Please wait', data['message'])

        # 3. Simulate time passing
        with app.app_context():
            user = User.query.filter_by(email=self.test_email).first()
            # Manually set expiry to 8 minutes from now (so > 9 minutes check fails, allowing new code)
            # Use naive UTC to match app behavior
            user.two_factor_code_expires = (datetime.now(timezone.utc) + timedelta(minutes=8)).replace(tzinfo=None)
            db.session.commit()

        # 4. Enable 2FA (Third request after "wait") - Should succeed
        response = self.client.post('/auth/2fa/enable', headers=headers)
        self.assertEqual(response.status_code, 200)

if __name__ == '__main__':
    unittest.main()
