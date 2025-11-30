from functools import wraps
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required


def admin_required(view_func=None, permission=None):
    """
    Decorator for function-based views that requires the user to be an administrator.

    - If the user is not authenticated, redirects to the login page
    - If the user is authenticated but not an admin (is_staff=False),
      redirects to the access_denied page
    - If permission is specified, checks if user has that specific permission
    - If the user is a superuser, always allows access
    - If the user is an admin (is_staff=True), allows access to the view

    Usage:
        @admin_required
        def my_view(request):
            ...

        @admin_required(permission='policies.add_policy')
        def create_policy(request):
            ...

    Requirements: 3.3, 3.5, 4.1
    """

    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            # Check if user is authenticated
            if not request.user.is_authenticated:
                return redirect("accounts:login")

            # Superusers always have access
            if request.user.is_superuser:
                return func(request, *args, **kwargs)

            # Check if user is an administrator
            if not request.user.is_staff:
                return redirect("accounts:access_denied")

            # If specific permission is required, check it
            if permission and not request.user.has_perm(permission):
                return redirect("accounts:access_denied")

            # User is authenticated and is an admin (or has permission), allow access
            return func(request, *args, **kwargs)

        return wrapper

    # Handle both @admin_required and @admin_required(permission='...')
    if view_func is not None:
        return decorator(view_func)
    return decorator
