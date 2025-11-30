from django.urls import path, re_path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    re_path(r"^media/(?P<path>.*)$", views.serve_media_file, name="serve_media"),
]
