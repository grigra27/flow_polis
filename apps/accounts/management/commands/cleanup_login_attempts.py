"""
Удаляет старые записи LoginAttempt чтобы таблица не росла бесконечно.

PLAN 9 (c): метод LoginAttempt.cleanup_old_attempts() существовал давно,
но никто его не вызывал по расписанию. Эта команда — обёртка для cron.

Рекомендуемый cron на сервере (раз в сутки в 4:30 утра по МСК):
  30 4 * * * cd /root/insurance_broker && \\
    docker-compose -f docker-compose.prod.yml exec -T web \\
    python manage.py cleanup_login_attempts \\
    >> /root/insurance_broker/logs/cleanup-login-attempts.log 2>&1
"""
from django.core.management.base import BaseCommand

from apps.accounts.models import LoginAttempt


class Command(BaseCommand):
    help = "Удаляет старые LoginAttempt записи (по умолчанию старше 30 дней)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Удалять записи старше N дней (default: 30)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только показать сколько было бы удалено, без реального удаления",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]

        if dry_run:
            from datetime import timedelta

            from django.utils import timezone

            cutoff = timezone.now() - timedelta(days=days)
            count = LoginAttempt.objects.filter(attempt_time__lt=cutoff).count()
            self.stdout.write(
                self.style.WARNING(
                    f"[dry-run] Удалилось бы {count} записей старше {days} дней"
                )
            )
            return

        deleted = LoginAttempt.cleanup_old_attempts(days=days)
        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Удалено {deleted} старых LoginAttempt записей (>{days} дней)"
            )
        )
