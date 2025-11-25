"""
Routes package for Medical Application API
"""
from routes.auth_routes import auth_ns
from routes.user_routes import user_ns
from routes.vlm_routes import vlm_ns
from routes.report_routes import reports_ns

__all__ = ['auth_ns', 'user_ns', 'vlm_ns', 'reports_ns']
