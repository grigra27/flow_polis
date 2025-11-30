"""
Property-based tests for brute force protection.

Feature: security-optimization-audit, Property 1: Блокировка после множественных неудачных попыток входа
Validates: Requirements 1.1
"""
import pytest
from hypothesis import given, strategies as st, settings, assume
from hypothesis.extra.django import TestCase
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import LoginAttempt


class TestBruteForceProtection(TestCase):
    """
    Property-based tests for brute force protection mechanism.

    Tests that the system correctly blocks IP addresses after multiple
    failed login attempts and unblocks them after the timeout period.
    """

    @given(
        ip_address=st.ip_addresses(v=4).map(str),
        failed_attempts=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=100, deadline=5000)
    def test_ip_blocked_after_five_failed_attempts(self, ip_address, failed_attempts):
        """
        Property 1: Блокировка после множественных неудачных попыток входа

        For any IP address, if there are 5 or more failed login attempts
        within 15 minutes, the next login attempt from that IP should be blocked
        for 30 minutes.

        Validates: Requirement 1.1
        """
        # Clean up any existing attempts for this IP
        LoginAttempt.objects.filter(ip_address=ip_address).delete()

        # Record the specified number of failed attempts
        # Spread them out slightly within the 15-minute window
        current_time = timezone.now()
        for i in range(failed_attempts):
            LoginAttempt.objects.create(
                ip_address=ip_address,
                username=f"user_{i}",
                success=False,
                attempt_time=current_time - timedelta(minutes=14, seconds=i),
            )

        # Check if IP is blocked
        is_blocked, unblock_time = LoginAttempt.is_ip_blocked(ip_address)

        # Property: IP should be blocked if and only if there are 5+ failed attempts
        if failed_attempts >= 5:
            assert (
                is_blocked
            ), f"IP {ip_address} should be blocked after {failed_attempts} failed attempts"
            assert (
                unblock_time is not None
            ), "Unblock time should be set when IP is blocked"

            # Verify unblock time is approximately 30 minutes from the 5th (oldest) attempt
            # The 5th attempt is at current_time - 14 minutes - 4 seconds
            expected_unblock = (
                current_time - timedelta(minutes=14, seconds=4) + timedelta(minutes=30)
            )
            time_diff = abs((unblock_time - expected_unblock).total_seconds())
            assert time_diff < 5, (
                f"Unblock time should be ~30 minutes from 5th attempt, "
                f"but difference is {time_diff} seconds"
            )
        else:
            assert (
                not is_blocked
            ), f"IP {ip_address} should NOT be blocked with only {failed_attempts} failed attempts"
            assert (
                unblock_time is None
            ), "Unblock time should be None when IP is not blocked"

    @given(
        ip_address=st.ip_addresses(v=4).map(str),
        minutes_ago=st.integers(min_value=46, max_value=120),
    )
    @settings(max_examples=100, deadline=5000)
    def test_old_attempts_dont_count_toward_blocking(self, ip_address, minutes_ago):
        """
        Property: Failed attempts older than 45 minutes should not cause blocking.

        For any IP address, failed login attempts that occurred more than
        45 minutes ago (15-minute window + 30-minute block) should not
        result in the IP being blocked.

        Validates: Requirement 1.1
        """
        # Clean up any existing attempts
        LoginAttempt.objects.filter(ip_address=ip_address).delete()

        # Record 5 failed attempts that are old enough that even if they
        # triggered a block, the block period has expired
        old_time = timezone.now() - timedelta(minutes=minutes_ago)
        for i in range(5):
            LoginAttempt.objects.create(
                ip_address=ip_address,
                username=f"user_{i}",
                success=False,
                attempt_time=old_time - timedelta(seconds=i),
            )

        # Check if IP is blocked
        is_blocked, unblock_time = LoginAttempt.is_ip_blocked(ip_address)

        # Property: Old attempts should not cause blocking
        assert (
            not is_blocked
        ), f"IP {ip_address} should NOT be blocked by attempts from {minutes_ago} minutes ago"
        assert unblock_time is None, "Unblock time should be None for old attempts"

    @given(
        ip_address=st.ip_addresses(v=4).map(str),
        successful_attempts=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100, deadline=5000)
    def test_successful_attempts_dont_cause_blocking(
        self, ip_address, successful_attempts
    ):
        """
        Property: Successful login attempts should not contribute to blocking.

        For any IP address, successful login attempts should not count
        toward the failed attempt threshold for blocking.

        Validates: Requirement 1.1
        """
        # Clean up any existing attempts
        LoginAttempt.objects.filter(ip_address=ip_address).delete()

        # Record successful attempts
        current_time = timezone.now()
        for i in range(successful_attempts):
            LoginAttempt.objects.create(
                ip_address=ip_address,
                username=f"user_{i}",
                success=True,
                attempt_time=current_time - timedelta(minutes=5),
            )

        # Check if IP is blocked
        is_blocked, unblock_time = LoginAttempt.is_ip_blocked(ip_address)

        # Property: Successful attempts should never cause blocking
        assert (
            not is_blocked
        ), f"IP {ip_address} should NOT be blocked by {successful_attempts} successful attempts"
        assert (
            unblock_time is None
        ), "Unblock time should be None for successful attempts"

    @given(
        ip_address=st.ip_addresses(v=4).map(str),
        minutes_since_fifth_attempt=st.integers(min_value=31, max_value=60),
    )
    @settings(max_examples=100, deadline=5000)
    def test_ip_unblocked_after_thirty_minutes(
        self, ip_address, minutes_since_fifth_attempt
    ):
        """
        Property: IP should be unblocked 30 minutes after the 5th failed attempt.

        For any IP address that was blocked, the block should be lifted
        30 minutes after the 5th failed attempt.

        Validates: Requirement 1.1
        """
        # Clean up any existing attempts
        LoginAttempt.objects.filter(ip_address=ip_address).delete()

        # Record 5 failed attempts that occurred more than 30 minutes ago
        old_time = timezone.now() - timedelta(minutes=minutes_since_fifth_attempt)
        for i in range(5):
            LoginAttempt.objects.create(
                ip_address=ip_address,
                username=f"user_{i}",
                success=False,
                attempt_time=old_time,
            )

        # Check if IP is blocked
        is_blocked, unblock_time = LoginAttempt.is_ip_blocked(ip_address)

        # Property: IP should be unblocked after 30 minutes
        assert not is_blocked, (
            f"IP {ip_address} should be unblocked {minutes_since_fifth_attempt} minutes "
            f"after the 5th failed attempt"
        )
        assert unblock_time is None, "Unblock time should be None after timeout expires"

    @given(
        ip_address=st.ip_addresses(v=4).map(str),
        failed_count=st.integers(min_value=5, max_value=10),
        successful_count=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=100, deadline=5000)
    def test_mixed_attempts_only_failed_count(
        self, ip_address, failed_count, successful_count
    ):
        """
        Property: Only failed attempts count toward blocking threshold.

        For any IP address with a mix of successful and failed attempts,
        only the failed attempts should count toward the blocking threshold.

        Validates: Requirement 1.1
        """
        # Clean up any existing attempts
        LoginAttempt.objects.filter(ip_address=ip_address).delete()

        # Record mixed attempts within the 15-minute window
        current_time = timezone.now()

        # Add failed attempts
        for i in range(failed_count):
            LoginAttempt.objects.create(
                ip_address=ip_address,
                username=f"failed_user_{i}",
                success=False,
                attempt_time=current_time - timedelta(minutes=10),
            )

        # Add successful attempts (should not affect blocking)
        for i in range(successful_count):
            LoginAttempt.objects.create(
                ip_address=ip_address,
                username=f"success_user_{i}",
                success=True,
                attempt_time=current_time - timedelta(minutes=10),
            )

        # Check if IP is blocked
        is_blocked, unblock_time = LoginAttempt.is_ip_blocked(ip_address)

        # Property: Should be blocked based only on failed attempts
        if failed_count >= 5:
            assert is_blocked, (
                f"IP {ip_address} should be blocked with {failed_count} failed attempts "
                f"(ignoring {successful_count} successful attempts)"
            )
        else:
            assert (
                not is_blocked
            ), f"IP {ip_address} should NOT be blocked with only {failed_count} failed attempts"

    @given(
        ip1=st.ip_addresses(v=4).map(str),
        ip2=st.ip_addresses(v=4).map(str),
    )
    @settings(max_examples=100, deadline=5000)
    def test_blocking_is_per_ip_address(self, ip1, ip2):
        """
        Property: Blocking is isolated per IP address.

        For any two different IP addresses, failed attempts from one IP
        should not affect the blocking status of another IP.

        Validates: Requirement 1.1
        """
        # Ensure IPs are different
        assume(ip1 != ip2)

        # Clean up any existing attempts
        LoginAttempt.objects.filter(ip_address__in=[ip1, ip2]).delete()

        # Record 5 failed attempts for ip1
        current_time = timezone.now()
        for i in range(5):
            LoginAttempt.objects.create(
                ip_address=ip1,
                username=f"user_{i}",
                success=False,
                attempt_time=current_time - timedelta(minutes=5),
            )

        # Check blocking status
        ip1_blocked, _ = LoginAttempt.is_ip_blocked(ip1)
        ip2_blocked, _ = LoginAttempt.is_ip_blocked(ip2)

        # Property: ip1 should be blocked, ip2 should not
        assert ip1_blocked, f"IP {ip1} should be blocked after 5 failed attempts"
        assert not ip2_blocked, f"IP {ip2} should NOT be blocked (no attempts recorded)"
