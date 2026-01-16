import firebase_admin
from firebase_admin import credentials, messaging
from flask import current_app
import os
from config import send_brevo_email, Config
from email_templates import get_profile_shared_email, get_report_uploaded_email
from models import UserDevice, User, Notification, db
from datetime import datetime, timezone

# Initialize Firebase Admin SDK
def initialize_firebase():
    try:
        # Check if already initialized
        if not firebase_admin._apps:
            cred_path = os.environ.get('FIREBASE_CREDENTIALS_PATH', 'firebase-adminsdk.json')
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                print("✅ Firebase Admin SDK initialized successfully")
            else:
                print(f"⚠️ Firebase credentials file not found at {cred_path}. Push notifications will not work.")
    except Exception as e:
        print(f"❌ Failed to initialize Firebase Admin SDK: {str(e)}")

def send_push_notification(user_id, title, body, data=None):
    """
    Send FCM push notification to all devices of a user
    """
    try:
        # Get user devices
        devices = UserDevice.query.filter_by(user_id=user_id).all()
        if not devices:
            print(f"ℹ️ No devices found for user {user_id}")
            return False

        tokens = [device.fcm_token for device in devices]

        notification = messaging.Notification(
            title=title,
            body=body,
        )

        android_config = messaging.AndroidConfig(
            priority='high',
            notification=messaging.AndroidNotification(
                channel_id='high_importance_channel',
                priority='high',
                default_sound=True,
                default_vibrate_timings=True
            )
        )

        apns_config = messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    sound='default',
                    content_available=True
                )
            )
        )

        if hasattr(messaging, 'send_multicast') and hasattr(messaging, 'MulticastMessage'):
            message = messaging.MulticastMessage(
                notification=notification,
                data=data or {},
                android=android_config,
                apns=apns_config,
                tokens=tokens,
            )

            response = messaging.send_multicast(message)
            print(f"✅ Sent push notification to {response.success_count} devices for user {user_id}")

            if response.failure_count > 0:
                responses = response.responses
                failed_tokens = []
                for idx, resp in enumerate(responses):
                    if not resp.success:
                        failed_tokens.append(tokens[idx])
                        print(f"❌ Failed to send to token {tokens[idx]}: {resp.exception}")

                if failed_tokens:
                    UserDevice.query.filter(UserDevice.fcm_token.in_(failed_tokens)).delete(synchronize_session=False)
                    from models import db
                    db.session.commit()
        else:
            print("⚠️ firebase_admin.messaging.send_multicast not available, falling back to per-token send()")
            for token in tokens:
                try:
                    message = messaging.Message(
                        notification=notification,
                        data=data or {},
                        android=android_config,
                        apns=apns_config,
                        token=token,
                    )
                    messaging.send(message)
                    print(f"✅ Sent push notification to token {token} for user {user_id}")
                except Exception as token_error:
                    print(f"❌ Failed to send to token {token}: {token_error}")

        return True
    except Exception as e:
        print(f"❌ Error sending push notification: {str(e)}")
        return False

def save_notification(user_id, title, message, notification_type, data=None):
    """
    Save notification to database for history
    """
    try:
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type=notification_type,
            data=data
        )
        db.session.add(notification)
        db.session.commit()
        return True
    except Exception as e:
        print(f"❌ Failed to save notification to DB: {str(e)}")
        return False

def notify_profile_share(sharer_name, profile_name, recipient_id, profile_id):
    """
    Notify user when a profile is shared with them
    """
    recipient = User.query.get(recipient_id)
    if not recipient:
        return

    # 1. Send Push Notification
    title = "New Profile Shared"
    body = f"{sharer_name} shared a medical profile with you: {profile_name}"
    data = {
        "type": "profile_share",
        "profile_id": str(profile_id),
        "click_action": "FLUTTER_NOTIFICATION_CLICK"
    }
    
    # Save to DB first
    save_notification(recipient_id, title, body, "profile_share", {"profile_id": profile_id})
    
    send_push_notification(recipient_id, title, body, data)

    # 2. Send Email - Disabled per user request (Notification only)
    # subject = f"{sharer_name} shared a profile with you on MediScan"
    # html_content = get_profile_shared_email(sharer_name, profile_name, recipient.first_name)
    # send_brevo_email(recipient.email, subject, html_content)

def notify_report_upload(uploader_name, profile_name, report_name, recipient_ids, profile_id, report_id):
    """
    Notify users when a report is uploaded to a shared profile
    """
    for recipient_id in recipient_ids:
        recipient = User.query.get(recipient_id)
        if not recipient:
            continue

        # 1. Send Push Notification
        title = "New Report Added"
        body = f"New report '{report_name}' added to {profile_name}"
        data = {
            "type": "report_upload",
            "profile_id": str(profile_id),
            "report_id": str(report_id),
            "click_action": "FLUTTER_NOTIFICATION_CLICK"
        }
        
        # Save to DB
        save_notification(recipient_id, title, body, "report_upload", {"profile_id": profile_id, "report_id": report_id})
        
        send_push_notification(recipient_id, title, body, data)

        # 2. Send Email (Only if recipient is elderly > 60 years old, or explicitly requested)
        # Calculate age
        should_send_email = True # Default to true for now to ensure visibility
        if recipient.date_of_birth:
            from datetime import date
            today = date.today()
            age = today.year - recipient.date_of_birth.year - ((today.month, today.day) < (recipient.date_of_birth.month, recipient.date_of_birth.day))
            # If age < 60, maybe skip email? 
            # For now, we will keep it enabled for everyone as it's a good feature, 
            # but we can easily restrict it here:
            # if age < 60: should_send_email = False
        
        if should_send_email:
            subject = f"New report added to {profile_name}"
            html_content = get_report_uploaded_email(uploader_name, profile_name, report_name, recipient.first_name)
            send_brevo_email(recipient.email, subject, html_content)
