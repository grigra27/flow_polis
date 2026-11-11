import json
import secrets

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import FlowPolicySource, in_force_q


def service_authorized(request):
    token = settings.FLOW_SERVICE_TOKEN
    return token and secrets.compare_digest(
        request.headers.get("Authorization", "").encode(), f"Bearer {token}".encode()
    )


def statuses(summary_ids):
    result = {pk: {"mode": None, "links": [], "total": 0} for pk in summary_ids}
    rows = (
        FlowPolicySource.objects.filter(pk__in=summary_ids)
        .annotate(in_force=in_force_q(timezone.localdate(), prefix="links__policy__"))
        .order_by("pk", "links__slot")
        .values_list(
            "pk",
            "mode",
            "total",
            "links__slot",
            "links__policy_id",
            "links__policy__policy_number",
            "in_force",
        )
    )
    for source_id, mode, total, slot, pk, number, in_force in rows:
        item = result[source_id]
        item.update(mode=mode, total=total)
        if pk is not None:
            item["links"].append(
                {
                    "position": slot or 1,
                    "policy_id": pk,
                    "policy_number": number,
                    "in_force": in_force,
                }
            )
    return result


@require_GET
@never_cache
def link_status(request, summary_id):
    if not service_authorized(request):
        return JsonResponse({"error": "unauthorized"}, status=401)
    return JsonResponse(statuses([summary_id])[summary_id])


@csrf_exempt
@require_POST
@never_cache
def batch_link_status(request):
    if not service_authorized(request):
        return JsonResponse({"error": "unauthorized"}, status=401)
    try:
        data = json.loads(request.body)
        ids = data["summary_ids"]
        if (
            not isinstance(ids, list)
            or len(ids) > 100
            or any(type(pk) is not int or not 1 <= pk < 2**63 for pk in ids)
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_summary_ids"}, status=400)
    return JsonResponse({"summaries": statuses(ids)})
