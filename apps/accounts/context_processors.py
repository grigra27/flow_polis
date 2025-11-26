def user_permissions(request):
    """
    Context processor that adds user permission information to all templates.
    
    Adds the following variables to template context:
    - is_admin: True if user is authenticated and is staff
    - is_regular_user: True if user is authenticated but not staff
    - can_edit: True if user is authenticated and is staff
    """
    return {
        'is_admin': request.user.is_authenticated and request.user.is_staff,
        'is_regular_user': request.user.is_authenticated and not request.user.is_staff,
        'can_edit': request.user.is_authenticated and request.user.is_staff,
    }
