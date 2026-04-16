from django.urls import path, re_path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("dashboard-v2/", views.dashboard_v2, name="dashboard_v2"),
    re_path(r"^media/(?P<path>.*)$", views.serve_media_file, name="serve_media"),
]
