from functools import wraps
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required


def admin_required(view_func):
    """
    Decorator for function-based views that requires the user to be an administrator.
    
    - If the user is not authenticated, redirects to the login page
    - If the user is authenticated but not an admin (is_staff=False), 
      redirects to the access_denied page
    - If the user is an admin (is_staff=True), allows access to the view
    
    Requirements: 3.3, 3.5, 4.1
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        
        # Check if user is an administrator
        if not request.user.is_staff:
            return redirect('accounts:access_denied')
        
        # User is authenticated and is an admin, allow access
        return view_func(request, *args, **kwargs)
    
    return wrapper
