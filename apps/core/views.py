from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta


@login_required
def dashboard(request):
    """
    Main dashboard view
    """
    from apps.policies.models import Policy, PaymentSchedule

    today = timezone.now().date()
    next_month = today + timedelta(days=30)

    # Statistics
    total_policies = Policy.objects.filter(policy_active=True).count()

    upcoming_payments = (
        PaymentSchedule.objects.filter(
            due_date__range=[today, next_month],
            paid_date__isnull=True,
            policy__policy_active=True,
        )
        .select_related("policy", "policy__client")
        .order_by("due_date", "policy__policy_number")
    )

    overdue_payments = (
        PaymentSchedule.objects.filter(
            due_date__lt=today, paid_date__isnull=True, policy__policy_active=True
        )
        .select_related("policy", "policy__client")
        .order_by("due_date", "policy__policy_number")
    )

    # Policies not uploaded
    not_uploaded_policies = Policy.objects.filter(policy_uploaded=False).select_related(
        "client", "insurer", "branch"
    )

    # Recent policies
    recent_policies = Policy.objects.select_related(
        "client", "insurer", "branch"
    ).order_by("-created_at")[:10]

    context = {
        "total_policies": total_policies,
        "upcoming_payments_count": upcoming_payments.count(),
        "overdue_payments_count": overdue_payments.count(),
        "upcoming_payments": upcoming_payments[:10],
        "overdue_payments": overdue_payments[:10],
        "not_uploaded_policies_count": not_uploaded_policies.count(),
        "not_uploaded_policies": not_uploaded_policies[:10],
        "recent_policies": recent_policies,
    }

    return render(request, "core/dashboard.html", context)


@login_required
def serve_media_file(request, path):
    """
    Serves media files with Content-Disposition header for security.
    Validates: Requirement 8.5

    This prevents inline execution of uploaded files by forcing download.
    """
    from django.http import FileResponse, Http404
    from django.conf import settings
    import os
    import mimetypes

    # Construct full file path
    file_path = os.path.join(settings.MEDIA_ROOT, path)

    # Check if file exists
    if not os.path.exists(file_path):
        raise Http404("File not found")

    # Check if path is within MEDIA_ROOT (prevent directory traversal)
    real_path = os.path.realpath(file_path)
    real_media_root = os.path.realpath(settings.MEDIA_ROOT)

    if not real_path.startswith(real_media_root):
        raise Http404("Invalid file path")

    # Get MIME type
    content_type, _ = mimetypes.guess_type(file_path)
    if content_type is None:
        content_type = "application/octet-stream"

    # Open file
    try:
        file_handle = open(file_path, "rb")
    except IOError:
        raise Http404("Cannot open file")

    # Create response with Content-Disposition header
    response = FileResponse(file_handle, content_type=content_type)

    # Set Content-Disposition to attachment to prevent inline execution
    filename = os.path.basename(file_path)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    # Additional security headers
    response["X-Content-Type-Options"] = "nosniff"

    return response
