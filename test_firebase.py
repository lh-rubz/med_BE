import firebase_admin
from firebase_admin import messaging
import sys

print(f"Firebase Admin Version: {firebase_admin.__version__}")
try:
    print(help(messaging.BatchResponse))
except Exception as e:
    print(f"Error accessing help: {e}")
