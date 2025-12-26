import unittest
from unittest.mock import patch, MagicMock
from app import app
from models import db, User
import json

class TestOAuthEndpoints(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = app.test_client()
        with app.app_context():
            db.create_all()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    @patch('routes.auth_routes.id_token.verify_oauth2_token')
    def test_google_auth_success(self, mock_verify):
        # Mock Google token verification response
        mock_verify.return_value = {
            'email': 'test@example.com',
            'sub': 'google_123',
            'given_name': 'Test',
            'family_name': 'User',
            'picture': 'http://example.com/pic.jpg'
        }

        response = self.client.post('/auth/google', 
                                    data=json.dumps({'id_token': 'fake_token'}),
                                    content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('access_token', data)
        self.assertEqual(data['user']['email'], 'test@example.com')

        # Verify user was created
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            self.assertIsNotNone(user)
            self.assertEqual(user.google_id, 'google_123')

    @patch('routes.auth_routes.requests.get')
    def test_facebook_auth_success(self, mock_get):
        # Mock Facebook Graph API response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'id': 'fb_123',
            'email': 'fb_test@example.com',
            'first_name': 'FB',
            'last_name': 'User',
            'picture': {'data': {'url': 'http://example.com/fb_pic.jpg'}}
        }
        mock_get.return_value = mock_response

        response = self.client.post('/auth/facebook', 
                                    data=json.dumps({'access_token': 'fake_fb_token'}),
                                    content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('access_token', data)
        self.assertEqual(data['user']['email'], 'fb_test@example.com')

        # Verify user was created
        with app.app_context():
            user = User.query.filter_by(email='fb_test@example.com').first()
            self.assertIsNotNone(user)
            self.assertEqual(user.facebook_id, 'fb_123')

if __name__ == '__main__':
    unittest.main()
