#!/usr/bin/env python
"""
Script to create a superuser for development
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser(
        username='admin',
        email='admin@example.com',
        password='admin'
    )
    print('Superuser created successfully!')
    print('Username: admin')
    print('Password: admin')
else:
    print('Superuser already exists')
