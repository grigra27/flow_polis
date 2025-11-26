from django import template

register = template.Library()


@register.simple_tag
def can_edit(user):
    """
    Check if user has permission to edit/create/delete content.
    Returns True if user is authenticated and is staff member.
    
    Usage in templates:
        {% load permission_tags %}
        {% can_edit request.user as user_can_edit %}
        {% if user_can_edit %}
            <!-- Show edit buttons -->
        {% endif %}
    """
    return user.is_authenticated and user.is_staff


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
