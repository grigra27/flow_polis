from django.contrib import admin
from .models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['client_name', 'client_inn']
    search_fields = ['client_name', 'client_inn']
    list_per_page = 50
