"""
Unit tests for LoginAttemptMiddleware and brute force protection.

Validates: Requirements 1.1
"""
import pytest
from django.test import TestCase, Client, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import LoginAttempt
from apps.accounts.middleware import LoginAttemptMiddleware


@pytest.mark.unit
class TestLoginAttemptMiddleware(TestCase):
    """
    Unit tests for the LoginAttemptMiddleware.

    Tests specific scenarios for brute force protection including
    successful logins, failed logins, and blocking behavior.
    """

    def setUp(self):
        """Set up test fixtures"""
        self.client = Client()
        self.factory = RequestFactory()

        # Create a test user
        self.user = User.objects.create_user(
            username="testuser", password="testpass123"
        )

        # Clean up any existing login attempts
        LoginAttempt.objects.all().delete()

    def test_successful_login_no_blocking(self):
        """
        Test: Successful login should not trigger blocking.

        A user should be able to log in successfully without
        being blocked, even after multiple successful attempts.

        Validates: Requirement 1.1
        """
        # Attempt to login successfully 10 times
        for i in range(10):
            response = self.client.post(
                "/accounts/login/", {"username": "testuser", "password": "testpass123"}
            )

            # Should redirect on success (not blocked)
            self.assertEqual(response.status_code, 302)

            # Logout for next iteration
            self.client.logout()

        # Verify no blocking is in effect
        is_blocked, _ = LoginAttempt.is_ip_blocked("127.0.0.1")
        self.assertFalse(is_blocked, "IP should not be blocked after successful logins")

    def test_blocking_after_five_failed_attempts(self):
        """
        Test: IP should be blocked after 5 failed login attempts.

        After 5 failed login attempts within 15 minutes,
        the IP should be blocked for 30 minutes.

        Validates: Requirement 1.1
        """
        # Make 5 failed login attempts
        for i in range(5):
            response = self.client.post(
                "/accounts/login/",
                {"username": "testuser", "password": "wrongpassword"},
            )

            # Should return 200 (login page with error) for first 5 attempts
            self.assertEqual(response.status_code, 200)

        # 6th attempt should be blocked
        response = self.client.post(
            "/accounts/login/", {"username": "testuser", "password": "wrongpassword"}
        )

        # Should return 403 (blocked)
        self.assertEqual(response.status_code, 403)
        # Check for Russian word "заблокирован" (blocked)
        self.assertIn("заблокирован".encode("utf-8"), response.content.lower())

    def test_unblocking_after_thirty_minutes(self):
        """
        Test: IP should be unblocked 30 minutes after the 5th failed attempt.

        After the 30-minute block period expires, the user should
        be able to attempt login again.

        Validates: Requirement 1.1
        """
        # Create 5 failed attempts that are 31 minutes old
        old_time = timezone.now() - timedelta(minutes=31)
        for i in range(5):
            LoginAttempt.objects.create(
                ip_address="127.0.0.1",
                username="testuser",
                success=False,
                attempt_time=old_time - timedelta(seconds=i),
            )

        # Verify IP is not blocked
        is_blocked, _ = LoginAttempt.is_ip_blocked("127.0.0.1")
        self.assertFalse(is_blocked, "IP should be unblocked after 30 minutes")

        # Should be able to attempt login
        response = self.client.post(
            "/accounts/login/", {"username": "testuser", "password": "wrongpassword"}
        )

        # Should return 200 (login page), not 403 (blocked)
        self.assertEqual(response.status_code, 200)

    def test_login_attempt_recording(self):
        """
        Test: Login attempts should be recorded in the database.

        Both successful and failed login attempts should be
        recorded with correct information.

        Validates: Requirement 1.1
        """
        # Make a failed attempt
        self.client.post(
            "/accounts/login/", {"username": "testuser", "password": "wrongpassword"}
        )

        # Verify it was recorded
        failed_attempts = LoginAttempt.objects.filter(
            username="testuser", success=False
        )
        self.assertEqual(failed_attempts.count(), 1)

        # Make a successful attempt
        self.client.post(
            "/accounts/login/", {"username": "testuser", "password": "testpass123"}
        )

        # Verify it was recorded
        successful_attempts = LoginAttempt.objects.filter(
            username="testuser", success=True
        )
        self.assertEqual(successful_attempts.count(), 1)

    def test_blocking_message_shows_remaining_time(self):
        """
        Test: Blocked page should show remaining time until unblock.

        When a user is blocked, they should see how long until
        they can try again.

        Validates: Requirement 1.1
        """
        # Create 5 recent failed attempts
        current_time = timezone.now()
        for i in range(5):
            LoginAttempt.objects.create(
                ip_address="127.0.0.1",
                username="testuser",
                success=False,
                attempt_time=current_time - timedelta(minutes=5, seconds=i),
            )

        # Try to login (should be blocked)
        response = self.client.post(
            "/accounts/login/", {"username": "testuser", "password": "wrongpassword"}
        )

        # Should be blocked
        self.assertEqual(response.status_code, 403)

        # Should show remaining time (approximately 25 minutes)
        content = response.content.decode("utf-8")
        self.assertIn("минут", content.lower())

    def test_different_ips_not_affected(self):
        """
        Test: Blocking one IP should not affect other IPs.

        Failed attempts from one IP should not cause blocking
        for different IP addresses.

        Validates: Requirement 1.1
        """
        # Create 5 failed attempts from a different IP
        for i in range(5):
            LoginAttempt.objects.create(
                ip_address="192.168.1.100",
                username="testuser",
                success=False,
                attempt_time=timezone.now() - timedelta(seconds=i),
            )

        # Verify that IP is blocked
        is_blocked, _ = LoginAttempt.is_ip_blocked("192.168.1.100")
        self.assertTrue(is_blocked)

        # But our test client IP (127.0.0.1) should not be blocked
        is_blocked, _ = LoginAttempt.is_ip_blocked("127.0.0.1")
        self.assertFalse(is_blocked)

        # Should be able to login from our IP
        response = self.client.post(
            "/accounts/login/", {"username": "testuser", "password": "testpass123"}
        )

        # Should redirect on success (not blocked)
        self.assertEqual(response.status_code, 302)

    def test_cleanup_old_attempts(self):
        """
        Test: Old login attempts can be cleaned up.

        The cleanup_old_attempts method should remove attempts
        older than the specified number of days.

        Validates: Requirement 1.1
        """
        # Create some old attempts (35 days old)
        old_time = timezone.now() - timedelta(days=35)
        for i in range(5):
            LoginAttempt.objects.create(
                ip_address="127.0.0.1",
                username="testuser",
                success=False,
                attempt_time=old_time,
            )

        # Create some recent attempts (5 days old)
        recent_time = timezone.now() - timedelta(days=5)
        for i in range(3):
            LoginAttempt.objects.create(
                ip_address="127.0.0.1",
                username="testuser",
                success=False,
                attempt_time=recent_time,
            )

        # Verify we have 8 attempts total
        self.assertEqual(LoginAttempt.objects.count(), 8)

        # Clean up attempts older than 30 days
        deleted_count = LoginAttempt.cleanup_old_attempts(days=30)

        # Should have deleted 5 old attempts
        self.assertEqual(deleted_count, 5)

        # Should have 3 recent attempts remaining
        self.assertEqual(LoginAttempt.objects.count(), 3)
