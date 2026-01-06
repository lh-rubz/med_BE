from flask import request
from flask_restx import Resource, Namespace, fields
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, FamilyConnection, Profile
from datetime import datetime

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
    'relationship': fields.String(required=True, description='Your relationship to them (e.g., Son, Caretaker)'),
    'access_level': fields.String(default='view', description='view or manage'),
    'profile_id': fields.Integer(description='Optional: ID of specific profile to share')
})

@connection_ns.route('/request')
class ConnectionRequest(Resource):
    @connection_ns.doc(security='Bearer Auth')
    @jwt_required()
    @connection_ns.expect(request_model)
    def post(self):
        """Send a connection request to another user"""
        current_user_id = int(get_jwt_identity())
        data = request.json
        print(f"DEBUG: Connection request received from {current_user_id} with data: {data}")
        
        receiver = User.query.filter_by(email=data['receiver_email']).first()
        if not receiver:
            print(f"DEBUG: Receiver email {data['receiver_email']} not found")
            return {'message': 'User with this email not found'}, 404
            
        if receiver.id == current_user_id:
            return {'message': 'Cannot connect to yourself'}, 400

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
            access_level=data.get('access_level', 'view'),
            profile_id=profile_id,
            status='pending'
        )
        
        db.session.add(new_conn)
        db.session.commit()
        
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
                {'id': c.id, 'to': c.receiver.email, 'status': c.status, 'relationship': c.relationship}
                for c in sent
            ],
            'received_requests': [
                {'id': c.id, 'from': c.requester.email, 'status': c.status, 'relationship': c.relationship}
                for c in received
            ]
        }
