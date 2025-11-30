from django.urls import path
from . import views

app_name = "insurers"

urlpatterns = [
    path("", views.InsurerListView.as_view(), name="list"),
    path("<int:pk>/", views.InsurerDetailView.as_view(), name="detail"),
    path("api/commission-rate/", views.get_commission_rate, name="api_commission_rate"),
]
