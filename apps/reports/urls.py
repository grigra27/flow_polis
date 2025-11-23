from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_index, name='index'),
    path('export/policies/', views.export_policies_excel, name='export_policies'),
    path('export/payments/', views.export_payments_excel, name='export_payments'),
]
