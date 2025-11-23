from django.urls import path
from . import views

app_name = 'policies'

urlpatterns = [
    path('', views.PolicyListView.as_view(), name='list'),
    path('<int:pk>/', views.PolicyDetailView.as_view(), name='detail'),
    path('payments/', views.PaymentScheduleListView.as_view(), name='payments'),
]
