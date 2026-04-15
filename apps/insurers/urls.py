from django.urls import path
from . import views

app_name = "insurers"

urlpatterns = [
    path("", views.InsurerListView.as_view(), name="list"),
    path("branches/", views.BranchListView.as_view(), name="branches_list"),
    path("branches/<int:pk>/", views.BranchDetailView.as_view(), name="branch_detail"),
    path("managers/", views.LeasingManagerListView.as_view(), name="managers_list"),
    path(
        "managers/<int:pk>/",
        views.LeasingManagerDetailView.as_view(),
        name="manager_detail",
    ),
    path("<int:pk>/", views.InsurerDetailView.as_view(), name="detail"),
    path("api/commission-rate/", views.get_commission_rate, name="api_commission_rate"),
]
