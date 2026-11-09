import secrets

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import FlowPolicySource


@require_GET
@never_cache
def link_status(request, summary_id):
    token = settings.FLOW_SERVICE_TOKEN
    if not token or not secrets.compare_digest(
        request.headers.get("Authorization", "").encode(), f"Bearer {token}".encode()
    ):
        return JsonResponse({"error": "unauthorized"}, status=401)
    source = FlowPolicySource.objects.filter(pk=summary_id).first()
    if source is None:
        return JsonResponse({"mode": None, "links": [], "total": 0})
    links = [
        {"position": slot or 1, "policy_id": pk, "policy_number": number}
        for slot, pk, number in source.links.order_by("slot").values_list(
            "slot", "policy_id", "policy__policy_number"
        )
    ]
    return JsonResponse({"mode": source.mode, "total": source.total, "links": links})
