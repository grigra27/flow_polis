#!/usr/bin/env python
"""
DEPRECATED: This script contains hardcoded credentials and should not be used.
Use the secure_create_superuser.py script instead.

This file is kept for reference only and should be removed in production.
"""

# SECURITY WARNING: This script contains hardcoded credentials
# DO NOT USE THIS SCRIPT IN PRODUCTION

# import os
# import django
#
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
# django.setup()
#
# from django.contrib.auth import get_user_model
#
# User = get_user_model()
#
# if not User.objects.filter(username='admin').exists():
#     User.objects.create_superuser(
#         username='admin',
#         email='admin@example.com',
#         password='admin'  # HARDCODED PASSWORD - SECURITY RISK
#     )
#     print('Superuser created successfully!')
#     print('Username: admin')
#     print('Password: admin')
# else:
#     print('Superuser already exists')

print("ERROR: This script is deprecated due to security concerns.")
print("Please use 'python secure_create_superuser.py' instead.")
print("Or use Django's built-in command: 'python manage.py createsuperuser'")
