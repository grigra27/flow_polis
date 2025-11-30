#!/usr/bin/env python
"""
Secure script to create a superuser with password prompt.
This script does not contain any hardcoded credentials.
"""
import os
import sys
import django
import getpass

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


def create_superuser_securely():
    """
    Create a superuser with secure password input.
    Validates password strength and prompts for confirmation.
    """
    print("=" * 60)
    print("Secure Superuser Creation")
    print("=" * 60)
    print()

    # Get username
    while True:
        username = input("Enter username: ").strip()
        if not username:
            print("Username cannot be empty. Please try again.")
            continue
        if User.objects.filter(username=username).exists():
            print(
                f"User '{username}' already exists. Please choose a different username."
            )
            continue
        break

    # Get email
    while True:
        email = input("Enter email address: ").strip()
        if not email:
            print("Email cannot be empty. Please try again.")
            continue
        if "@" not in email:
            print("Invalid email format. Please try again.")
            continue
        break

    # Get password with validation
    while True:
        password = getpass.getpass("Enter password: ")
        if not password:
            print("Password cannot be empty. Please try again.")
            continue

        # Validate password strength
        try:
            validate_password(password)
        except ValidationError as e:
            print("\nPassword validation failed:")
            for error in e.messages:
                print(f"  - {error}")
            print("\nPlease choose a stronger password.\n")
            continue

        # Confirm password
        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            print("Passwords do not match. Please try again.\n")
            continue

        break

    # Create the superuser
    try:
        user = User.objects.create_superuser(
            username=username, email=email, password=password
        )
        print("\n" + "=" * 60)
        print("✓ Superuser created successfully!")
        print("=" * 60)
        print(f"Username: {username}")
        print(f"Email: {email}")
        print("\nYou can now log in with these credentials.")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n✗ Error creating superuser: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(create_superuser_securely())
