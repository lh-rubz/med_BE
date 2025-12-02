"""
Google Drive Upload Utility

Handles file uploads to Google Drive using service account authentication.
"""

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
import io
import os
import requests


# Configuration
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'service_account.json'
PARENT_FOLDER_ID = "1AWU7gaaZ4W8XUl08Slml0FHVZhpPEHSY"  # Hardcoded folder ID


def get_authorized_session(credentials):
    """Create an authorized session with proxy support"""
    # Get proxy settings from environment
    proxies = {}
    http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
    https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
    
    if http_proxy:
        proxies['http'] = http_proxy
    if https_proxy:
        proxies['https'] = https_proxy
    
    # Create session with proxy
    session = requests.Session()
    if proxies:
        session.proxies.update(proxies)
    
    # Create authorized session
    authed_session = AuthorizedSession(credentials)
    if proxies:
        authed_session.proxies.update(proxies)
    
    return authed_session


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
        
        # Build service with proxy support
        http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
        https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
        
        # Use custom HTTP with proxy if available
        if http_proxy or https_proxy:
            import httplib2
            http = httplib2.Http(timeout=60)
            # Set proxy manually on http object
            if https_proxy:
                proxy_url = https_proxy.replace('http://', '').replace('https://', '')
                if ':' in proxy_url:
                    proxy_host, proxy_port = proxy_url.rsplit(':', 1)
                else:
                    proxy_host, proxy_port = proxy_url, '8080'
                http.proxy_info = httplib2.ProxyInfo(
                    proxy_type=3,  # PROXY_TYPE_HTTP
                    proxy_host=proxy_host,
                    proxy_port=int(proxy_port)
                )
            service = build('drive', 'v3', credentials=creds, http=http)
        else:
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
        
        # Build service with proxy support
        http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
        https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
        
        if http_proxy or https_proxy:
            import httplib2
            http = httplib2.Http(timeout=60)
            if https_proxy:
                proxy_url = https_proxy.replace('http://', '').replace('https://', '')
                if ':' in proxy_url:
                    proxy_host, proxy_port = proxy_url.rsplit(':', 1)
                else:
                    proxy_host, proxy_port = proxy_url, '8080'
                http.proxy_info = httplib2.ProxyInfo(
                    proxy_type=3,  # PROXY_TYPE_HTTP
                    proxy_host=proxy_host,
                    proxy_port=int(proxy_port)
                )
            service = build('drive', 'v3', credentials=creds, http=http)
        else:
            service = build('drive', 'v3', credentials=creds)
            
        service.files().delete(fileId=file_id).execute()
        return True
    except Exception as e:
        print(f"Delete error: {str(e)}")
        return False
