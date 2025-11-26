def user_permissions(request):
    """
    Context processor that adds user permission information to all templates.
    
    Adds the following variables to template context:
    - is_admin: True if user is authenticated and is staff
    - is_regular_user: True if user is authenticated but not staff
    - can_edit: True if user is authenticated and is staff (or superuser)
    - is_superuser: True if user is a superuser
    - user_perms: User's permission object for checking specific permissions in templates
    """
    user = request.user
    return {
        'is_admin': user.is_authenticated and user.is_staff,
        'is_regular_user': user.is_authenticated and not user.is_staff,
        'can_edit': user.is_authenticated and (user.is_staff or user.is_superuser),
        'is_superuser': user.is_authenticated and user.is_superuser,
        'user_perms': user if user.is_authenticated else None,
    }
