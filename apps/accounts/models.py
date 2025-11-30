"""
Models for accounts app.
Validates: Requirements 1.1, 1.5
"""
from django.db import models
from django.utils import timezone
from datetime import timedelta


class LoginAttempt(models.Model):
    """
    Tracks login attempts for brute force protection.

    Validates: Requirements 1.1 (blocking after 5 failed attempts),
               1.5 (logging suspicious activity)
    """

    ip_address = models.GenericIPAddressField(verbose_name="IP-адрес", db_index=True)
    username = models.CharField(
        max_length=150, verbose_name="Имя пользователя", db_index=True
    )
    attempt_time = models.DateTimeField(
        default=timezone.now, verbose_name="Время попытки", db_index=True
    )
    success = models.BooleanField(default=False, verbose_name="Успешная попытка")
    user_agent = models.TextField(blank=True, verbose_name="User Agent")

    class Meta:
        verbose_name = "Попытка входа"
        verbose_name_plural = "Попытки входа"
        ordering = ["-attempt_time"]
        indexes = [
            models.Index(fields=["ip_address", "attempt_time"]),
            models.Index(fields=["username", "attempt_time"]),
        ]

    def __str__(self):
        status = "успешная" if self.success else "неудачная"
        return f"{self.username} с {self.ip_address} - {status} ({self.attempt_time})"

    @classmethod
    def is_ip_blocked(cls, ip_address):
        """
        Check if an IP address is blocked due to too many failed attempts.

        An IP is blocked if there are 5 or more failed login attempts
        within a 15-minute window, and the block lasts for 30 minutes
        from the time of the 5th failed attempt.

        Args:
            ip_address: The IP address to check

        Returns:
            tuple: (is_blocked: bool, unblock_time: datetime or None)
        """
        now = timezone.now()

        # Look back 45 minutes (15 min window + 30 min block period)
        # to find any blocking period that might still be active
        lookback_time = now - timedelta(minutes=45)

        # Get all failed attempts from this IP, ordered by time (newest first)
        failed_attempts = cls.objects.filter(
            ip_address=ip_address, success=False, attempt_time__gte=lookback_time
        ).order_by("-attempt_time")

        if failed_attempts.count() < 5:
            return False, None

        # Check each possible 15-minute window to see if there are 5+ attempts
        # Start from the most recent attempt and work backwards
        for i in range(failed_attempts.count() - 4):
            # Get the i-th attempt (0-indexed)
            first_attempt = failed_attempts[i]
            # Get the (i+4)-th attempt (the 5th in this window)
            fifth_attempt = failed_attempts[i + 4]

            # Check if these 5 attempts are within a 15-minute window
            time_diff = first_attempt.attempt_time - fifth_attempt.attempt_time

            if time_diff <= timedelta(minutes=15):
                # Found a window with 5+ attempts within 15 minutes
                # Block is active for 30 minutes from the 5th attempt
                unblock_time = fifth_attempt.attempt_time + timedelta(minutes=30)

                if now < unblock_time:
                    return True, unblock_time

        return False, None

    @classmethod
    def record_attempt(cls, ip_address, username, success, user_agent=""):
        """
        Record a login attempt.

        Args:
            ip_address: The IP address of the attempt
            username: The username used in the attempt
            success: Whether the attempt was successful
            user_agent: The user agent string (optional)

        Returns:
            LoginAttempt: The created LoginAttempt instance
        """
        return cls.objects.create(
            ip_address=ip_address,
            username=username,
            success=success,
            user_agent=user_agent,
        )

    @classmethod
    def cleanup_old_attempts(cls, days=30):
        """
        Clean up login attempts older than specified days.

        This should be run periodically (e.g., via a cron job or Celery task)
        to prevent the table from growing indefinitely.

        Args:
            days: Number of days to keep (default: 30)

        Returns:
            int: Number of deleted records
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        deleted_count, _ = cls.objects.filter(attempt_time__lt=cutoff_date).delete()
        return deleted_count
