"""
Middleware for permission checking and brute force protection.
Validates: Requirements 1.1, 1.5, 3.5, 4.1, 12.1, 12.3, 12.5
"""
import re
import logging
from django.shortcuts import redirect, render
from django.http import HttpResponseForbidden
from django.urls import reverse
from django.utils import timezone
from apps.core.security_utils import SecurityEventLogger

logger = logging.getLogger(__name__)


class LoginAttemptMiddleware:
    """
    Middleware to track login attempts and block IPs after too many failures.

    Blocks an IP address for 30 minutes after 5 failed login attempts
    within a 15-minute window.

    Validates: Requirements 1.1 (blocking after failed attempts),
               1.5 (logging suspicious activity)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only check on login page POST requests
        if request.path == reverse("accounts:login") and request.method == "POST":
            # Import here to avoid circular imports
            from apps.accounts.models import LoginAttempt

            # Get client IP address
            ip_address = self.get_client_ip(request)

            # Check if IP is blocked
            is_blocked, unblock_time = LoginAttempt.is_ip_blocked(ip_address)

            if is_blocked:
                # Log the blocked attempt
                logger.warning(
                    f"Blocked login attempt from IP {ip_address} - "
                    f"too many failed attempts. Unblock time: {unblock_time}"
                )
                SecurityEventLogger.log_brute_force_detected(
                    ip_address=ip_address,
                    username=request.POST.get("username", "unknown"),
                    attempt_count=5,
                )

                # Calculate remaining time
                remaining_time = unblock_time - timezone.now()
                minutes_remaining = int(remaining_time.total_seconds() / 60)

                # Return a blocked response
                context = {
                    "error_message": (
                        f"Слишком много неудачных попыток входа. "
                        f"Попробуйте снова через {minutes_remaining} минут."
                    ),
                    "unblock_time": unblock_time,
                }
                return render(
                    request, "accounts/login_blocked.html", context, status=403
                )

        # Continue processing the request
        response = self.get_response(request)

        # After processing, if this was a login attempt, record it
        if request.path == reverse("accounts:login") and request.method == "POST":
            from apps.accounts.models import LoginAttempt

            ip_address = self.get_client_ip(request)
            username = request.POST.get("username", "")
            user_agent = request.META.get("HTTP_USER_AGENT", "")

            # Check if login was successful by checking if user is authenticated
            # after the response was generated
            success = hasattr(request, "user") and request.user.is_authenticated

            # Record the attempt
            LoginAttempt.record_attempt(
                ip_address=ip_address,
                username=username,
                success=success,
                user_agent=user_agent,
            )

            # Log the login attempt
            if success:
                SecurityEventLogger.log_successful_login(username, ip_address)
            else:
                SecurityEventLogger.log_failed_login(username, ip_address, user_agent)

            # Log suspicious activity if multiple IPs are trying the same username
            if not success:
                self.check_suspicious_activity(username)

        return response

    def get_client_ip(self, request):
        """
        Get the client's IP address from the request.

        Handles cases where the request comes through a proxy (X-Forwarded-For).

        Args:
            request: The HTTP request object

        Returns:
            str: The client's IP address
        """
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            # Take the first IP in the list (client IP)
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip

    def check_suspicious_activity(self, username):
        """
        Check for suspicious activity patterns.

        Logs a warning if the same username has failed login attempts
        from more than 3 different IP addresses within the last hour.

        Validates: Requirement 1.5 (logging suspicious activity)

        Args:
            username: The username to check
        """
        from apps.accounts.models import LoginAttempt

        # Get the time 1 hour ago
        time_threshold = timezone.now() - timezone.timedelta(hours=1)

        # Get distinct IP addresses that failed to login with this username
        distinct_ips = (
            LoginAttempt.objects.filter(
                username=username, success=False, attempt_time__gte=time_threshold
            )
            .values("ip_address")
            .distinct()
            .count()
        )

        if distinct_ips > 3:
            logger.warning(
                f"Suspicious activity detected: Username '{username}' has failed "
                f"login attempts from {distinct_ips} different IP addresses in the last hour"
            )
            SecurityEventLogger.log_suspicious_activity(
                event_type="multiple_ip_login_attempts",
                details={
                    "username": username,
                    "distinct_ips": distinct_ips,
                    "time_window": "1 hour",
                },
            )


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
            r"^/admin/",  # Admin panel
            r".*/create/$",  # Create URLs
            r".*/edit/$",  # Edit URLs (generic)
            r".*/\d+/edit/$",  # Edit URLs with ID
            r".*/update/$",  # Update URLs (generic)
            r".*/\d+/update/$",  # Update URLs with ID
            r".*/delete/$",  # Delete URLs (generic)
            r".*/\d+/delete/$",  # Delete URLs with ID
        ]
        # Compile patterns for better performance
        self.compiled_patterns = [
            re.compile(pattern) for pattern in self.protected_patterns
        ]

    def __call__(self, request):
        # Check if the current URL matches any protected pattern
        if self.is_protected_url(request.path):
            # Check if user is authenticated
            if not request.user.is_authenticated:
                # Redirect to login page with next parameter
                login_url = reverse("accounts:login")
                return redirect(f"{login_url}?next={request.path}")

            # Superusers always have access
            if request.user.is_superuser:
                response = self.get_response(request)
                return response

            # Check if user has admin privileges (is_staff)
            if not request.user.is_staff:
                # Log unauthorized access attempt
                logger.warning(
                    f"Unauthorized access attempt by user {request.user.username} "
                    f"to protected URL {request.path}"
                )
                # Get client IP
                ip_address = self.get_client_ip(request)
                SecurityEventLogger.log_access_denied(
                    user=request.user.username, url=request.path, ip_address=ip_address
                )
                # Return 403 Forbidden
                return HttpResponseForbidden(
                    "You do not have permission to access this page. "
                    "Only administrators can perform this action."
                )

            # User is staff but not superuser - permissions will be checked by views
            # (views should use @admin_required(permission='...') or AdminRequiredMixin with permission_required)

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

    def get_client_ip(self, request):
        """
        Get the client's IP address from the request.

        Args:
            request: The HTTP request object

        Returns:
            str: The client's IP address
        """
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR", "unknown")
        return ip
