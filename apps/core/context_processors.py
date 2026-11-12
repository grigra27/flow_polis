from django.conf import settings


def service_navigation(request):
    return {"requests_home_url": f"{settings.FLOW_ZS_BASE_URL.rstrip('/')}/requests/"}
