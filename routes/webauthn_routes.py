from flask import request, session, jsonify, make_response
from flask_restx import Resource, Namespace, fields
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    options_to_json,
    base64url_to_bytes,
    generate_authentication_options,
    verify_authentication_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)

from models import db, User, Authenticator
from config import Config

webauthn_ns = Namespace('auth/webauthn', description='WebAuthn (Biometric) Authentication')

# --- helper models for documentation ---
# (Simplified for brevity as inputs are complex JSONs from browser)
register_options_model = webauthn_ns.model('WebAuthnRegisterOptions', {
    'email': fields.String(description='User email (for identification)')
})

verify_register_model = webauthn_ns.model('WebAuthnVerifyRegister', {
    'email': fields.String(required=True),
    'response': fields.Raw(description='Navigator credential response')
})

login_options_model = webauthn_ns.model('WebAuthnLoginOptions', {
    'email': fields.String(description='User email')
})

verify_login_model = webauthn_ns.model('WebAuthnVerifyLogin', {
    'email': fields.String(required=True),
    'response': fields.Raw(description='Navigator credential response')
})


@webauthn_ns.route('/register/options')
class RegisterOptions(Resource):
    @jwt_required() 
    def post(self):
        """Generate registration options for a new credential (requires JWT)"""
        # User must be logged in to register a passkey
        # We also need their user object to associate the credential
        
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404

        # Check if user already has credentials? (Optional, we allow multiple)
        
        # 1. Generate options
        simple_registration_options = generate_registration_options(
            rp_id=Config.RP_ID,
            rp_name=Config.RP_NAME,
            user_id=str(user.id).encode('utf-8'), # binary user ID
            user_name=user.email,
            user_display_name=f"{user.first_name} {user.last_name or ''}",
            authenticator_selection=AuthenticatorSelectionCriteria(
                user_verification=UserVerificationRequirement.PREFERRED
            ),
            supported_pub_key_algs=[-7, -257], # ES256, RS256
        )
        
        # 2. Store challenge in session (stateful) OR return it signed (stateless)
        # For simplicity in this stack, we'll try to use Flask session if available (cookie based).
        # NOTE: If API is purely stateless (JWT only), we need a way to verify the challenge later.
        # Common pattern: Return challenge to client, client sends it back, we just accept it? NO, INSECURE.
        # Secure pattern (Stateless): Sign the challenge with our SECRET_KEY and return it as a token to the client.
        # But `webauthn` library expects us to pass the 'expected_challenge'.
        # Let's use a temporary caching mechanism or DB. 
        # Actually, simpler: Store challenge in the User model temporarily? Or a dedicated 'WebAuthnChallenge' table.
        # For this implementation, let's use a global simple cache or session if using browser cookies.
        # Given this is likely called from a mobile app or SPA, sticky sessions are tricky.
        # Let's put the challenge in the DB on the User model temporarily (add a column or use `verification_code` field abuse? No).
        # Let's add a temporary `current_challenge` column to User model or just Authenticator table?.
        # Valid strategy: Cache.
        
        # Let's just use a simple in-memory dict for this prototype if single worker.
        # BUT for production, use Redis. 
        # As a fallback: I will store it in the `verification_code` field of the user temporarily (prefixed with 'wa:')?
        # Better: Add `webauthn_challenge` to User model? I can't edit model easily again without migration.
        # Let's use `reset_code` field as a temporary storage since user is logged in and not resetting password? 
        # No, that's hacky.
        # Implementation Detail: I will modify User model again to add `webauthn_challenge`.
        pass
        
        # ACTUALLY: Flask Session IS available if client supports cookies. 
        # If not, we have to return the challenge signed.
        # Let's assume client handles cookies or we accept a partial state.
        
        session['wa_challenge'] = simple_registration_options.challenge
        session['wa_user_id'] = user.id
        
        return options_to_json(simple_registration_options)


@webauthn_ns.route('/register/verify')
class RegisterVerify(Resource):
    @jwt_required()
    def post(self):
        """Verify the credential creation response"""
        data = request.json
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404

        challenge = session.get('wa_challenge')
        if not challenge:
            return {'message': 'Challenge not found or session expired'}, 400

        try:
            verification = verify_registration_response(
                credential=data,
                expected_challenge=base64url_to_bytes(challenge),
                expected_origin=Config.RP_ORIGIN,
                expected_rp_id=Config.RP_ID,
                require_user_verification=True, 
            )
            
            # Save credential to DB
            new_auth = Authenticator(
                user_id=user.id,
                credential_id=verification.credential_id,
                public_key=verification.credential_public_key,
                sign_count=verification.sign_count,
                transports=",".join(data.get("response", {}).get("transports", []))
            )
            db.session.add(new_auth)
            db.session.commit()
            
            session.pop('wa_challenge', None) # cleanup
            return {'message': 'Passkey registered successfully!'}, 200
            
        except Exception as e:
            return {'message': f'Verification failed: {str(e)}'}, 400


@webauthn_ns.route('/login/options')
class LoginOptions(Resource):
    def post(self):
        """Get login options (challenge) for a user"""
        data = request.json
        email = data.get('email')
        
        if not email:
            return {'message': 'Email is required'}, 400
            
        user = User.query.filter_by(email=email).first()
        if not user:
             return {'message': 'User not found'}, 404
             
        # Get user's authenticators
        authenticators = Authenticator.query.filter_by(user_id=user.id).all()
        
        if not authenticators:
            return {'message': 'No passkeys found for this user'}, 404
            
        simple_auth_options = generate_authentication_options(
            rp_id=Config.RP_ID,
            allow_credentials=[PublicKeyCredentialDescriptor(id=auth.credential_id) for auth in authenticators],
            user_verification=UserVerificationRequirement.PREFERRED
        )
        
        session['wa_challenge'] = simple_auth_options.challenge
        session['wa_user_id'] = user.id
        
        return options_to_json(simple_auth_options)


@webauthn_ns.route('/login/verify')
class LoginVerify(Resource):
    def post(self):
        """Verify login assertion response"""
        data = request.json
        email = data.get('email') # Or identify by handle
        
        # We need to find *which* authenticator was used (from credential ID in response)
        credential_id_b64 = data.get('id')
        
        # Find user and the specific authenticator
        # In a real flow, we might look up authenticator by ID globally, but filtering by user is safer if we know user
        challenge = session.get('wa_challenge')
        user_id = session.get('wa_user_id')
        
        if not challenge or not user_id:
             return {'message': 'Session expired or invalid flow'}, 400
             
        user = User.query.get(user_id)
        if not user:
            return {'message': 'User mismatch'}, 400
            
        # Find the authenticator used
        authenticator = None
        for auth in user.authenticators:
             # basic b64 check (needs decoding to be robust, but webauthn lib helps?)
             # Actually verify_authentication_response takes the list and finds it, OR we pass the specific key.
             # We should find the auth object to update sign count.
             # Let's blindly try to verify first? No, we need the public key.
             # Convert DB valid credential IDs to match request ID?
             # For simplicity:
             if auth.credential_id == base64url_to_bytes(credential_id_b64):
                 authenticator = auth
                 break
        
        if not authenticator:
             return {'message': 'Unknown credential used'}, 400

        try:
            verification = verify_authentication_response(
                credential=data,
                expected_challenge=base64url_to_bytes(challenge),
                expected_origin=Config.RP_ORIGIN,
                expected_rp_id=Config.RP_ID,
                credential_public_key=authenticator.public_key,
                credential_current_sign_count=authenticator.sign_count,
            )
            
            # Update sign count
            authenticator.sign_count = verification.new_sign_count
            authenticator.last_used_at = db.func.now()
            db.session.commit()
            
            # Log user in
            access_token = create_access_token(identity=str(user.id))
            session.pop('wa_challenge', None)
            
            return {
                'message': 'Login successful',
                'access_token': access_token,
                'user': {
                    'email': user.email,
                    'first_name': user.first_name,
                    'biometric_login': True
                }
            }, 200
            
        except Exception as e:
            return {'message': f'Authentication failed: {str(e)}'}, 400
