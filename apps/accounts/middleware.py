"""
Middleware for permission checking.
Validates: Requirements 3.5, 4.1
"""
import re
import logging
from django.shortcuts import redirect
from django.http import HttpResponseForbidden
from django.urls import reverse

logger = logging.getLogger(__name__)


class PermissionCheckMiddleware:
    """
    Middleware to check user permissions for protected URLs.
    
    Protects URLs that involve creating, editing, updating, or deleting data.
    Only authenticated users with is_staff=True can access these URLs.
    
    Validates: Requirements 3.5 (blocking regular users), 4.1 (allowing admins)
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        # Define protected URL patterns
        self.protected_patterns = [
            r'^/admin/',           # Admin panel
            r'.*/create/$',        # Create URLs
            r'.*/edit/$',          # Edit URLs (generic)
            r'.*/\d+/edit/$',      # Edit URLs with ID
            r'.*/update/$',        # Update URLs (generic)
            r'.*/\d+/update/$',    # Update URLs with ID
            r'.*/delete/$',        # Delete URLs (generic)
            r'.*/\d+/delete/$',    # Delete URLs with ID
        ]
        # Compile patterns for better performance
        self.compiled_patterns = [re.compile(pattern) for pattern in self.protected_patterns]
    
    def __call__(self, request):
        # Check if the current URL matches any protected pattern
        if self.is_protected_url(request.path):
            # Check if user is authenticated
            if not request.user.is_authenticated:
                # Redirect to login page with next parameter
                login_url = reverse('accounts:login')
                return redirect(f'{login_url}?next={request.path}')
            
            # Check if user has admin privileges (is_staff)
            if not request.user.is_staff:
                # Log unauthorized access attempt
                logger.warning(
                    f"Unauthorized access attempt by user {request.user.username} "
                    f"to protected URL {request.path}"
                )
                # Return 403 Forbidden
                return HttpResponseForbidden(
                    "You do not have permission to access this page. "
                    "Only administrators can perform this action."
                )
        
        # Continue processing the request
        response = self.get_response(request)
        return response
    
    def is_protected_url(self, path):
        """
        Check if the given path matches any protected URL pattern.
        
        Args:
            path: The URL path to check
            
        Returns:
            bool: True if the path is protected, False otherwise
        """
        for pattern in self.compiled_patterns:
            if pattern.search(path):
                return True
        return False
