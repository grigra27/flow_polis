from django.contrib.auth.mixins import UserPassesTestMixin, PermissionRequiredMixin
from django.shortcuts import redirect


class AdminRequiredMixin(UserPassesTestMixin):
    """
    Mixin for class-based views that requires the user to be an administrator.

    - If the user is not authenticated, redirects to the login page
    - If the user is authenticated but not an admin (is_staff=False),
      redirects to the access_denied page
    - If permission_required is set, checks for specific permission
    - Superusers always have access
    - If the user is an admin (is_staff=True), allows access to the view

    Usage:
        class MyView(AdminRequiredMixin, View):
            ...

        class CreatePolicyView(AdminRequiredMixin, CreateView):
            permission_required = 'policies.add_policy'
            ...

    Requirements: 3.3, 3.5, 4.1
    """

    permission_required = None  # Can be set in subclass for specific permission check

    def test_func(self):
        """
        Test if the user is an administrator and has required permissions.

        Returns:
            bool: True if user is authenticated and has access, False otherwise
        """
        user = self.request.user

        # User must be authenticated
        if not user.is_authenticated:
            return False

        # Superusers always have access
        if user.is_superuser:
            return True

        # User must be staff
        if not user.is_staff:
            return False

        # If specific permission is required, check it
        if self.permission_required:
            if isinstance(self.permission_required, str):
                return user.has_perm(self.permission_required)
            else:
                # Multiple permissions
                return all(user.has_perm(perm) for perm in self.permission_required)

        # User is staff and no specific permission required
        return True

    def handle_no_permission(self):
        """
        Handle the case when the user doesn't have permission.

        - If user is not authenticated, redirect to login page (handled by parent class)
        - If user is authenticated but not admin, redirect to access_denied page

        Returns:
            HttpResponse: Redirect to appropriate page
        """
        if self.request.user.is_authenticated:
            # User is authenticated but not an admin or lacks permission
            return redirect("accounts:access_denied")

        # User is not authenticated, let parent class handle (redirect to login)
        return super().handle_no_permission()
