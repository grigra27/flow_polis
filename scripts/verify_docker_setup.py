#!/usr/bin/env python3
"""
Verification script for Docker production setup.
This script checks that all components are properly configured before deployment.
"""

import subprocess
import sys
import time
from pathlib import Path


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color


def print_header(text):
    """Print a section header."""
    print(f"\n{Colors.BLUE}{'=' * 60}{Colors.NC}")
    print(f"{Colors.BLUE}{text}{Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 60}{Colors.NC}\n")


def print_success(text):
    """Print a success message."""
    print(f"{Colors.GREEN}✓{Colors.NC} {text}")


def print_error(text):
    """Print an error message."""
    print(f"{Colors.RED}✗{Colors.NC} {text}")


def print_info(text):
    """Print an info message."""
    print(f"{Colors.YELLOW}ℹ{Colors.NC} {text}")


def run_command(cmd, capture_output=True, check=False):
    """Run a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=capture_output,
            text=True,
            check=check
        )
        return result
    except subprocess.CalledProcessError as e:
        return e


def check_docker_installed():
    """Check if Docker is installed."""
    print("Checking Docker installation...")
    result = run_command("docker --version")
    if result.returncode == 0:
        print_success(f"Docker is installed: {result.stdout.strip()}")
        return True
    else:
        print_error("Docker is not installed")
        print_info("Install Docker Desktop from https://www.docker.com/products/docker-desktop")
        return False


def check_docker_running():
    """Check if Docker daemon is running."""
    print("\nChecking if Docker is running...")
    result = run_command("docker info")
    if result.returncode == 0:
        print_success("Docker daemon is running")
        return True
    else:
        print_error("Docker daemon is not running")
        print_info("Start Docker Desktop")
        return False


def check_environment_files():
    """Check if required environment files exist."""
    print("\nChecking environment files...")
    files_ok = True
    
    env_prod = Path(".env.prod")
    if env_prod.exists():
        print_success(".env.prod exists")
    else:
        print_error(".env.prod not found")
        print_info("Create .env.prod from .env.prod.example")
        files_ok = False
    
    env_prod_db = Path(".env.prod.db")
    if env_prod_db.exists():
        print_success(".env.prod.db exists")
    else:
        print_error(".env.prod.db not found")
        print_info("Create .env.prod.db from .env.prod.db.example")
        files_ok = False
    
    return files_ok


def check_compose_syntax():
    """Validate docker-compose.prod.yml syntax."""
    print("\nValidating docker-compose.prod.yml syntax...")
    result = run_command("docker compose -f docker-compose.prod.yml config --quiet")
    if result.returncode == 0:
        print_success("docker-compose.prod.yml syntax is valid")
        return True
    else:
        print_error("docker-compose.prod.yml has syntax errors")
        print(result.stderr)
        return False


def check_required_files():
    """Check if all required files exist."""
    print("\nChecking required files...")
    files_ok = True
    
    required_files = [
        "docker-compose.prod.yml",
        "Dockerfile",
        "entrypoint.sh",
        "requirements.txt",
        "nginx/default.conf",
    ]
    
    for file_path in required_files:
        path = Path(file_path)
        if path.exists():
            print_success(f"{file_path} exists")
        else:
            print_error(f"{file_path} not found")
            files_ok = False
    
    return files_ok


def check_services_running():
    """Check if Docker services are running."""
    print("\nChecking if services are running...")
    print_info("If services are not running, start them with:")
    print_info("  docker compose -f docker-compose.prod.yml up -d")
    
    result = run_command("docker compose -f docker-compose.prod.yml ps --format json")
    if result.returncode != 0:
        print_error("Could not check service status")
        return False
    
    if not result.stdout.strip():
        print_info("No services are currently running")
        return False
    
    services = ['db', 'redis', 'web', 'celery_worker', 'celery_beat', 'nginx']
    all_running = True
    
    for service in services:
        service_result = run_command(
            f"docker compose -f docker-compose.prod.yml ps --format json {service}"
        )
        if service_result.stdout.strip():
            # Service exists, check if running
            if '"State":"running"' in service_result.stdout:
                print_success(f"{service} is running")
            else:
                print_error(f"{service} is not running")
                all_running = False
        else:
            print_error(f"{service} not found")
            all_running = False
    
    return all_running


def check_database_connection():
    """Check if web service can connect to database."""
    print("\nChecking database connection...")
    result = run_command(
        "docker compose -f docker-compose.prod.yml exec -T web "
        "python manage.py check --database default"
    )
    if result.returncode == 0:
        print_success("Web service can connect to PostgreSQL")
        return True
    else:
        print_error("Web service cannot connect to PostgreSQL")
        print(result.stderr)
        return False


def check_celery_connection():
    """Check if Celery can connect to Redis."""
    print("\nChecking Celery connection to Redis...")
    result = run_command(
        "docker compose -f docker-compose.prod.yml exec -T celery_worker "
        "celery -A config inspect ping"
    )
    if result.returncode == 0 and 'pong' in result.stdout.lower():
        print_success("Celery worker can connect to Redis")
        return True
    else:
        print_error("Celery worker cannot connect to Redis")
        return False


def check_nginx_accessibility():
    """Check if Nginx is accessible."""
    print("\nChecking Nginx accessibility...")
    result = run_command(
        "curl -s -o /dev/null -w '%{http_code}' http://localhost:80/admin/login/"
    )
    if result.returncode == 0:
        http_code = result.stdout.strip()
        if http_code in ['200', '302', '301']:
            print_success(f"Nginx is accessible (HTTP {http_code})")
            return True
    
    print_error("Nginx is not accessible")
    return False


def check_static_files():
    """Check if static files are being served."""
    print("\nChecking static file serving...")
    result = run_command(
        "curl -s -o /dev/null -w '%{http_code}' http://localhost:80/static/admin/css/base.css"
    )
    if result.returncode == 0 and result.stdout.strip() == '200':
        print_success("Static files are being served correctly")
        return True
    else:
        print_error("Static files are not being served")
        print_info("Run: docker compose -f docker-compose.prod.yml exec web "
                   "python manage.py collectstatic --noinput")
        return False


def run_integration_tests():
    """Run integration tests."""
    print("\nRunning integration tests...")
    print_info("This may take a few minutes...")
    
    result = run_command(
        "python -m pytest tests/test_docker_integration.py -v",
        capture_output=False
    )
    
    if result.returncode == 0:
        print_success("All integration tests passed")
        return True
    else:
        print_error("Some integration tests failed")
        return False


def main():
    """Main verification function."""
    print_header("Docker Production Setup Verification")
    
    checks = [
        ("Docker Installation", check_docker_installed),
        ("Docker Running", check_docker_running),
        ("Environment Files", check_environment_files),
        ("Required Files", check_required_files),
        ("Docker Compose Syntax", check_compose_syntax),
    ]
    
    # Run basic checks
    all_passed = True
    for check_name, check_func in checks:
        if not check_func():
            all_passed = False
    
    if not all_passed:
        print_header("Pre-flight Checks Failed")
        print_error("Please fix the issues above before proceeding")
        return 1
    
    print_header("Basic Checks Passed")
    print_info("Now checking running services...")
    
    # Check if services are running
    services_running = check_services_running()
    
    if not services_running:
        print_header("Services Not Running")
        print_info("Start services with:")
        print_info("  docker compose -f docker-compose.prod.yml up -d")
        print_info("\nThen run this script again to verify the running services")
        return 0
    
    # Run service checks
    service_checks = [
        ("Database Connection", check_database_connection),
        ("Celery Connection", check_celery_connection),
        ("Nginx Accessibility", check_nginx_accessibility),
        ("Static Files", check_static_files),
    ]
    
    all_services_ok = True
    for check_name, check_func in service_checks:
        if not check_func():
            all_services_ok = False
    
    if not all_services_ok:
        print_header("Service Checks Failed")
        print_error("Please fix the issues above before proceeding")
        return 1
    
    # Run integration tests
    print_header("Running Integration Tests")
    tests_passed = run_integration_tests()
    
    if tests_passed:
        print_header("All Checks Passed! ✓")
        print_success("Your Docker production setup is working correctly")
        print_info("\nNext steps:")
        print_info("  1. Review deployment documentation: docs/DEPLOYMENT.md")
        print_info("  2. Prepare Digital Ocean Droplet (Task 17)")
        print_info("  3. Configure DNS (Task 18)")
        print_info("  4. Deploy to production (Task 19)")
        return 0
    else:
        print_header("Integration Tests Failed")
        print_error("Please investigate test failures before deploying to production")
        return 1


if __name__ == "__main__":
    sys.exit(main())
