from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import redirect


class AdminRequiredMixin(UserPassesTestMixin):
    """
    Mixin for class-based views that requires the user to be an administrator.
    
    - If the user is not authenticated, redirects to the login page
    - If the user is authenticated but not an admin (is_staff=False), 
      redirects to the access_denied page
    - If the user is an admin (is_staff=True), allows access to the view
    
    Usage:
        class MyView(AdminRequiredMixin, View):
            ...
    
    Requirements: 3.3, 3.5, 4.1
    """
    
    def test_func(self):
        """
        Test if the user is an administrator.
        
        Returns:
            bool: True if user is authenticated and is_staff=True, False otherwise
        """
        return self.request.user.is_authenticated and self.request.user.is_staff
    
    def handle_no_permission(self):
        """
        Handle the case when the user doesn't have permission.
        
        - If user is not authenticated, redirect to login page (handled by parent class)
        - If user is authenticated but not admin, redirect to access_denied page
        
        Returns:
            HttpResponse: Redirect to appropriate page
        """
        if self.request.user.is_authenticated:
            # User is authenticated but not an admin
            return redirect('accounts:access_denied')
        
        # User is not authenticated, let parent class handle (redirect to login)
        return super().handle_no_permission()
