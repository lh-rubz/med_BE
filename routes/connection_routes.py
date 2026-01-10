from flask import request
from flask_restx import Resource, Namespace, fields
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, FamilyConnection, Profile, Notification, ProfileShare
from datetime import datetime
import json

connection_ns = Namespace('connections', description='Family Connection operations')

connection_model = connection_ns.model('Connection', {
    'id': fields.Integer(readOnly=True),
    'requester_id': fields.Integer(),
    'receiver_id': fields.Integer(),
    'relationship': fields.String(required=True),
    'status': fields.String(),
    'access_level': fields.String(),
    'created_at': fields.String()
})

request_model = connection_ns.model('ConnectionRequest', {
    'receiver_email': fields.String(required=True, description='Email of the person you want access to'),
    'relationship': fields.String(required=True, description='Your relationship to them (e.g., Son, Caretaker, Doctor)'),
    'access_level': fields.String(default='view', description='Access level: view (Read Only), upload (Read & Upload), manage (Full Access)'),
    'profile_id': fields.Integer(description='Optional: ID of specific profile to share')
})

@connection_ns.route('/request')
class ConnectionRequest(Resource):
    @connection_ns.doc(security='Bearer Auth')
    @jwt_required()
    @connection_ns.expect(request_model)
    def post(self):
        """
        Send a connection request to another user
        
        Access Levels:
        - 'view': Read Only (Viewer) - Can view reports and profiles
        - 'upload': Read & Upload (Contributor) - Can view and upload reports
        - 'manage': Full Access (Manager) - Can view, upload, edit, delete, and share
        """
        current_user_id = int(get_jwt_identity())
        data = request.json
        print(f"DEBUG: Connection request received from {current_user_id} with data: {data}")
        
        receiver = User.query.filter_by(email=data['receiver_email']).first()
        if not receiver:
            print(f"DEBUG: Receiver email {data['receiver_email']} not found")
            return {'message': 'User with this email not found'}, 404
            
        if receiver.id == current_user_id:
            return {'message': 'Cannot connect to yourself'}, 400

        # Validate access_level
        access_level = data.get('access_level', 'view')
        valid_access_levels = ['view', 'upload', 'manage']
        if access_level not in valid_access_levels:
            return {
                'message': f'Invalid access_level. Must be one of: {", ".join(valid_access_levels)}',
                'valid_levels': valid_access_levels
            }, 400

        # Validate profile_id if provided
        profile_id = data.get('profile_id')
        if profile_id:
            profile = Profile.query.get(profile_id)
            if not profile:
                 return {'message': f'Profile with ID {profile_id} not found'}, 404
            # Optionally check ownership?
            if profile.creator_id != current_user_id:
                print(f"DEBUG: User {current_user_id} does not own profile {profile_id}")
                # return {'message': 'You can only share profiles you own'}, 403 # Optional enforcement

        # Check for existing connection
        # If profile_id is provided, check if we already have a connection for this specific profile
        # If not provided, check if we have a generic connection
        query = FamilyConnection.query.filter_by(
            requester_id=current_user_id, 
            receiver_id=receiver.id
        )
        
        if profile_id:
            # Check if this specific profile is already shared/requested
            existing = query.filter_by(profile_id=profile_id).first()
            if existing:
                msg = f'Connection request for this profile already exists with status: {existing.status}'
                print(f"DEBUG: {msg}")
                return {'message': msg}, 400
        else:
            # Check if a general connection already exists
            # Note: This might overlap if we want to allow general + specific connections. 
            # For now, let's just check for exact match of "no profile" or "any connection"? 
            # Let's keep strict check to avoid spam.
            existing = query.first()
            if existing and not existing.profile_id:
                 msg = f'General connection already exists with status: {existing.status}'
                 print(f"DEBUG: {msg}")
                 return {'message': msg}, 400

        new_conn = FamilyConnection(
            requester_id=current_user_id,
            receiver_id=receiver.id,
            relationship=data['relationship'],
            access_level=access_level,
            profile_id=profile_id,
            status='pending'
        )
        
        db.session.add(new_conn)

        # Notify Receiver
        try:
            requester = User.query.get(current_user_id)
            requester_name = f"{requester.first_name} {requester.last_name or ''}".strip()
            title = 'New Connection Request'
            msg = f"{requester_name} sent you a connection request."
            
            notification_data = {
                'connection_id': new_conn.id, 
                'requester_id': requester.id
            }
            
            notification = Notification(
                user_id=receiver.id,
                title=title,
                message=msg,
                notification_type='connection_request',
                data=json.dumps(notification_data)
            )
            db.session.add(notification)
            
            # Send Push Notification (Heads-up)
            from utils.notification_service import send_push_notification
            
            # Add click_action for Flutter to handle navigation
            push_data = notification_data.copy()
            push_data['type'] = 'connection_request'
            push_data['click_action'] = 'FLUTTER_NOTIFICATION_CLICK'
            
            # Commit first to ensure notification ID is generated (optional, but good practice)
            db.session.commit()
            
            send_push_notification(receiver.id, title, msg, push_data)
            
        except Exception as e:
            print(f"Error sending notification: {e}")
            # Ensure we commit transaction if notification fails but connection succeeded
            try:
                db.session.commit()
            except:
                pass

        # In a real app, send email notification here
        return {'message': 'Connection request sent', 'id': new_conn.id}, 201

@connection_ns.route('/<int:id>/respond')
class ConnectionRespond(Resource):
    @connection_ns.doc(security='Bearer Auth')
    @jwt_required()
    def post(self, id):
        """Accept or reject a pending connection request"""
        current_user_id = int(get_jwt_identity())
        data = request.json
        action = data.get('action') # 'accept' or 'reject'
        
        conn = FamilyConnection.query.filter_by(id=id, receiver_id=current_user_id).first()
        if not conn:
            return {'message': 'Connection request not found'}, 404
            
        if conn.status != 'pending':
            return {'message': 'Request already processed'}, 400
            
        if action == 'accept':
            conn.status = 'accepted'
            
            # Scenario 1: Specific Profile Share
            if conn.profile_id:
                # Create ProfileShare record so it shows up in shared_profiles list
                existing_share = ProfileShare.query.filter_by(
                    profile_id=conn.profile_id,
                    shared_with_user_id=conn.receiver_id
                ).first()
                
                if not existing_share:
                    new_share = ProfileShare(
                        profile_id=conn.profile_id,
                        shared_with_user_id=conn.receiver_id,
                        access_level=conn.access_level
                    )
                    db.session.add(new_share)
                    
            # Scenario 2: Generic User Link (Old "Family Member" logic)
            else:
                # Automatically create a Profile entry for the linked user in the requester's account
                # This makes it easy to filter reports by "Father"
                new_profile = Profile(
                    creator_id=conn.requester_id,
                    linked_user_id=conn.receiver_id,
                    first_name=conn.receiver.first_name,
                    last_name=conn.receiver.last_name,
                    relationship=conn.relationship
                )
                db.session.add(new_profile)
        else:
            conn.status = 'rejected'
            
        db.session.commit()
        return {'message': f'Connection {action}ed successfully'}

@connection_ns.route('/')
class ConnectionList(Resource):
    @connection_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self):
        """List all active family connections (sent and received)"""
        current_user_id = int(get_jwt_identity())
        
        sent = FamilyConnection.query.filter_by(requester_id=current_user_id).all()
        received = FamilyConnection.query.filter_by(receiver_id=current_user_id).all()
        
        return {
            'sent_requests': [
                {
                    'id': c.id,
                    'to': c.receiver.email,
                    'status': c.status,
                    'relationship': c.relationship,
                    'access_level': c.access_level or 'view',
                    'profile_id': c.profile_id
                }
                for c in sent
            ],
            'received_requests': [
                {
                    'id': c.id,
                    'from': c.requester.email,
                    'status': c.status,
                    'relationship': c.relationship,
                    'access_level': c.access_level or 'view',
                    'profile_id': c.profile_id
                }
                for c in received
            ]
        }
