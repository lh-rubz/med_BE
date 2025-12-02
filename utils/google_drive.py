"""
Google Drive Upload Utility

Handles file uploads to Google Drive using service account authentication.
"""

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account
import io


# Configuration
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'service_account.json'
PARENT_FOLDER_ID = "1AWU7gaaZ4W8XUl08Slml0FHVZhpPEHSY"  # Hardcoded folder ID


def authenticate():
    """Authenticate with Google Drive using service account"""
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, 
            scopes=SCOPES
        )
        return creds
    except Exception as e:
        print(f"Authentication error: {str(e)}")
        raise


def upload_file_to_drive(file_data, filename, mimetype='image/jpeg'):
    """
    Upload a file to Google Drive
    
    Args:
        file_data: File data as bytes or file-like object
        filename: Name for the file in Google Drive
        mimetype: MIME type of the file (default: image/jpeg)
    
    Returns:
        dict: File information including id, name, and webViewLink
    """
    try:
        creds = authenticate()
        service = build('drive', 'v3', credentials=creds)

        file_metadata = {
            'name': filename,
            'parents': [PARENT_FOLDER_ID] if PARENT_FOLDER_ID else []
        }

        # Handle both bytes and file paths
        if isinstance(file_data, bytes):
            media = MediaIoBaseUpload(
                io.BytesIO(file_data),
                mimetype=mimetype,
                resumable=True
            )
        else:
            # Assume it's a file path
            media = MediaIoBaseUpload(
                open(file_data, 'rb'),
                mimetype=mimetype,
                resumable=True
            )

        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webViewLink, webContentLink'
        ).execute()

        # Make the file publicly accessible (optional)
        try:
            service.permissions().create(
                fileId=file['id'],
                body={'type': 'anyone', 'role': 'reader'}
            ).execute()
        except Exception as perm_error:
            print(f"Warning: Could not set public permissions: {str(perm_error)}")

        return {
            'id': file.get('id'),
            'name': file.get('name'),
            'webViewLink': file.get('webViewLink'),
            'webContentLink': file.get('webContentLink'),
            'directLink': f"https://drive.google.com/uc?export=view&id={file.get('id')}"
        }

    except Exception as e:
        print(f"Upload error: {str(e)}")
        raise


def delete_file_from_drive(file_id):
    """
    Delete a file from Google Drive
    
    Args:
        file_id: Google Drive file ID
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        creds = authenticate()
        service = build('drive', 'v3', credentials=creds)
        service.files().delete(fileId=file_id).execute()
        return True
    except Exception as e:
        print(f"Delete error: {str(e)}")
        return False
