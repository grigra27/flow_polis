"""
Security middleware for input validation.
Validates: Requirements 3.3, 3.4, 12.1, 12.3, 12.5
"""
import logging
from django.http import HttpResponseBadRequest
from .security_utils import InputSanitizer, SecurityEventLogger

logger = logging.getLogger(__name__)


class InputValidationMiddleware:
    """
    Middleware to validate and sanitize user input.
    Validates: Requirements 3.3, 3.4
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Validate GET parameters
        if request.GET:
            for key, value in request.GET.items():
                if isinstance(value, str):
                    is_valid, _ = InputSanitizer.validate_and_sanitize(value)
                    if not is_valid:
                        ip_address = self.get_client_ip(request)
                        logger.warning(
                            f"Potential SQL injection detected in GET parameter '{key}' "
                            f"from IP {ip_address}"
                        )
                        SecurityEventLogger.log_sql_injection_attempt(
                            ip_address=ip_address, input_value=value, field=f"GET:{key}"
                        )
                        return HttpResponseBadRequest("Invalid input detected")

        # Validate POST parameters
        if request.POST:
            for key, value in request.POST.items():
                if isinstance(value, str):
                    is_valid, _ = InputSanitizer.validate_and_sanitize(value)
                    if not is_valid:
                        ip_address = self.get_client_ip(request)
                        logger.warning(
                            f"Potential SQL injection detected in POST parameter '{key}' "
                            f"from IP {ip_address}"
                        )
                        SecurityEventLogger.log_sql_injection_attempt(
                            ip_address=ip_address,
                            input_value=value,
                            field=f"POST:{key}",
                        )
                        return HttpResponseBadRequest("Invalid input detected")

        response = self.get_response(request)
        return response

    @staticmethod
    def get_client_ip(request):
        """Get client IP address from request."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip
