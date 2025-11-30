from django import template

register = template.Library()


@register.simple_tag
def can_edit(user, permission=None):
    """
    Check if user has permission to edit/create/delete content.
    Returns True if user is authenticated and is staff member (or superuser).
    If permission is specified, checks for that specific permission.

    Usage in templates:
        {% load permission_tags %}
        {% can_edit request.user as user_can_edit %}
        {% if user_can_edit %}
            <!-- Show edit buttons -->
        {% endif %}

        {% can_edit request.user 'policies.add_policy' as can_add_policy %}
        {% if can_add_policy %}
            <!-- Show add policy button -->
        {% endif %}
    """
    if not user.is_authenticated:
        return False

    # Superusers always have access
    if user.is_superuser:
        return True

    # User must be staff
    if not user.is_staff:
        return False

    # If specific permission is required, check it
    if permission:
        return user.has_perm(permission)

    # User is staff
    return True


@register.simple_tag
def can_access_admin(user):
    """
    Check if user has permission to access admin panel.
    Returns True if user is authenticated and is staff member.

    Usage in templates:
        {% load permission_tags %}
        {% can_access_admin request.user as user_can_access %}
        {% if user_can_access %}
            <!-- Show admin link -->
        {% endif %}
    """
    return user.is_authenticated and user.is_staff


@register.simple_tag
def has_perm(user, permission):
    """
    Check if user has a specific permission.

    Usage in templates:
        {% load permission_tags %}
        {% has_perm request.user 'policies.add_policy' as can_add %}
        {% if can_add %}
            <!-- Show add button -->
        {% endif %}
    """
    if not user.is_authenticated:
        return False

    return user.has_perm(permission)
