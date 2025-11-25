"""
Integration tests for Docker environment.

**Feature: docker-deployment, Property 1: Персистентность данных при перезапуске контейнеров**
**Feature: docker-deployment, Property 4: Автоматический перезапуск упавших контейнеров**
**Validates: Требования 1.2, 1.3, 1.5, 6.1, 6.2, 6.3, 7.1, 7.3, 7.4, 7.5**
"""
import subprocess
import time
import unittest
import json
import os
import tempfile
from pathlib import Path


class DockerComposeTestCase(unittest.TestCase):
    """Base test case for Docker Compose integration tests."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment."""
        cls.compose_file = 'docker-compose.prod.yml'
        cls.project_name = 'insurance_broker_test'
        
    def run_compose_command(self, command, capture_output=True, check=True):
        """Run a docker compose command."""
        cmd = ['docker', 'compose', '-f', self.compose_file, '-p', self.project_name] + command
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            check=check
        )
        return result
    
    def get_container_status(self, service_name):
        """Get the status of a container."""
        result = self.run_compose_command(['ps', '--format', 'json', service_name])
        if result.stdout.strip():
            # Parse each line as JSON (docker compose ps outputs one JSON per line)
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if line.strip():
                    container_info = json.loads(line)
                    if container_info.get('Service') == service_name:
                        return container_info.get('State', 'unknown')
        return 'not_found'
    
    def wait_for_service_healthy(self, service_name, timeout=120, interval=5):
        """Wait for a service to become healthy."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                result = self.run_compose_command(
                    ['ps', '--format', 'json', service_name],
                    check=False
                )
                if result.stdout.strip():
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        if line.strip():
                            container_info = json.loads(line)
                            if container_info.get('Service') == service_name:
                                health = container_info.get('Health', '')
                                state = container_info.get('State', '')
                                
                                if health == 'healthy' or (state == 'running' and not health):
                                    return True
            except Exception as e:
                print(f"Error checking service {service_name}: {e}")
            
            time.sleep(interval)
        
        return False
    
    def get_container_id(self, service_name):
        """Get the container ID for a service."""
        result = self.run_compose_command(['ps', '-q', service_name])
        return result.stdout.strip()


class TestDockerContainerStartup(DockerComposeTestCase):
    """
    Test that all Docker containers start successfully.
    **Validates: Требования 1.2, 1.3**
    """
    
    def test_all_containers_start(self):
        """Test that all required containers start successfully."""
        # Define required services
        required_services = ['db', 'redis', 'web', 'celery_worker', 'celery_beat', 'nginx']
        
        print("\nStarting Docker Compose services...")
        
        # Start services
        self.run_compose_command(['up', '-d'], capture_output=False)
        
        # Wait a bit for containers to initialize
        time.sleep(10)
        
        # Check each service
        for service in required_services:
            with self.subTest(service=service):
                status = self.get_container_status(service)
                self.assertIn(status, ['running', 'healthy'], 
                            f"Service {service} is not running (status: {status})")
        
        print("All containers started successfully")
    
    @classmethod
    def tearDownClass(cls):
        """Clean up after tests."""
        # Note: We keep containers running for subsequent tests
        pass


class TestDatabaseConnection(DockerComposeTestCase):
    """
    Test web container connection to PostgreSQL.
    **Validates: Требования 1.3, 6.1**
    """
    
    def test_web_connects_to_postgresql(self):
        """Test that web container can connect to PostgreSQL."""
        print("\nTesting web to PostgreSQL connection...")
        
        # Wait for services to be healthy
        self.assertTrue(
            self.wait_for_service_healthy('db', timeout=60),
            "PostgreSQL service did not become healthy"
        )
        self.assertTrue(
            self.wait_for_service_healthy('web', timeout=120),
            "Web service did not become healthy"
        )
        
        # Test database connection by running a Django command
        result = self.run_compose_command([
            'exec', '-T', 'web',
            'python', 'manage.py', 'check', '--database', 'default'
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Database connection check failed: {result.stderr}")
        
        print("Web successfully connected to PostgreSQL")
    
    def test_database_migrations_run(self):
        """Test that database migrations can be executed."""
        print("\nTesting database migrations...")
        
        # Run migrations
        result = self.run_compose_command([
            'exec', '-T', 'web',
            'python', 'manage.py', 'migrate', '--noinput'
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Migrations failed: {result.stderr}")
        
        print("Database migrations completed successfully")


class TestCeleryRedisConnection(DockerComposeTestCase):
    """
    Test Celery worker connection to Redis.
    **Validates: Требования 7.1, 7.3**
    """
    
    def test_celery_connects_to_redis(self):
        """Test that Celery worker can connect to Redis."""
        print("\nTesting Celery to Redis connection...")
        
        # Wait for services to be healthy
        self.assertTrue(
            self.wait_for_service_healthy('redis', timeout=60),
            "Redis service did not become healthy"
        )
        self.assertTrue(
            self.wait_for_service_healthy('celery_worker', timeout=120),
            "Celery worker service did not become healthy"
        )
        
        # Check Celery worker status
        result = self.run_compose_command([
            'exec', '-T', 'celery_worker',
            'celery', '-A', 'config', 'inspect', 'ping'
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Celery ping failed: {result.stderr}")
        self.assertIn('pong', result.stdout.lower(),
                     "Celery worker did not respond with pong")
        
        print("Celery successfully connected to Redis")
    
    def test_celery_beat_connects_to_redis(self):
        """Test that Celery beat can connect to Redis."""
        print("\nTesting Celery Beat to Redis connection...")
        
        # Check if celery_beat container is running
        status = self.get_container_status('celery_beat')
        self.assertEqual(status, 'running',
                        f"Celery beat is not running (status: {status})")
        
        # Check logs for successful connection
        result = self.run_compose_command([
            'logs', '--tail', '50', 'celery_beat'
        ], check=False)
        
        # Look for signs of successful startup (no connection errors)
        self.assertNotIn('ConnectionError', result.stdout,
                        "Celery beat has connection errors")
        
        print("Celery Beat successfully connected to Redis")


class TestNginxAccess(DockerComposeTestCase):
    """
    Test application accessibility through Nginx.
    **Validates: Требования 1.5, 2.2**
    """
    
    def test_nginx_is_accessible(self):
        """Test that Nginx is accessible on port 80."""
        print("\nTesting Nginx accessibility...")
        
        # Wait for Nginx to be healthy
        self.assertTrue(
            self.wait_for_service_healthy('nginx', timeout=60),
            "Nginx service did not become healthy"
        )
        
        # Test HTTP access to Nginx
        result = subprocess.run(
            ['curl', '-f', '-s', '-o', '/dev/null', '-w', '%{http_code}',
             'http://localhost:80/admin/login/'],
            capture_output=True,
            text=True,
            check=False
        )
        
        # Should get a response (200, 302, etc., but not connection refused)
        self.assertIn(result.stdout, ['200', '302', '301'],
                     f"Nginx did not respond correctly (HTTP {result.stdout})")
        
        print("Nginx is accessible on port 80")
    
    def test_nginx_proxies_to_web(self):
        """Test that Nginx proxies requests to the web container."""
        print("\nTesting Nginx proxy to web...")
        
        # Make a request through Nginx
        result = subprocess.run(
            ['curl', '-s', 'http://localhost:80/admin/login/'],
            capture_output=True,
            text=True,
            check=False
        )
        
        # Should get Django admin login page
        self.assertIn('Django', result.stdout,
                     "Response does not appear to be from Django")
        
        print("Nginx successfully proxies to web container")


class TestStaticFiles(DockerComposeTestCase):
    """
    Test static file collection and serving.
    **Validates: Требования 1.5, 2.3**
    """
    
    def test_static_files_collected(self):
        """Test that static files are collected successfully."""
        print("\nTesting static file collection...")
        
        # Run collectstatic
        result = self.run_compose_command([
            'exec', '-T', 'web',
            'python', 'manage.py', 'collectstatic', '--noinput'
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"collectstatic failed: {result.stderr}")
        
        print("Static files collected successfully")
    
    def test_nginx_serves_static_files(self):
        """Test that Nginx serves static files directly."""
        print("\nTesting Nginx static file serving...")
        
        # First ensure static files are collected
        self.run_compose_command([
            'exec', '-T', 'web',
            'python', 'manage.py', 'collectstatic', '--noinput'
        ], check=False)
        
        # Try to access a static file through Nginx
        # Django admin has static files we can test
        result = subprocess.run(
            ['curl', '-f', '-s', '-o', '/dev/null', '-w', '%{http_code}',
             'http://localhost:80/static/admin/css/base.css'],
            capture_output=True,
            text=True,
            check=False
        )
        
        # Should get 200 OK for static file
        self.assertEqual(result.stdout, '200',
                        f"Static file not served correctly (HTTP {result.stdout})")
        
        print("Nginx serves static files successfully")


class TestDataPersistence(DockerComposeTestCase):
    """
    Test data persistence across container restarts.
    **Property 1: Персистентность данных при перезапуске контейнеров**
    **Validates: Требования 6.1, 6.2, 6.3**
    """
    
    def test_postgres_data_persists_after_restart(self):
        """
        Test that PostgreSQL data persists after container restart.
        **Property 1: Персистентность данных при перезапуске контейнеров**
        """
        print("\nTesting PostgreSQL data persistence...")
        
        # Create a test table and insert data
        create_sql = """
        CREATE TABLE IF NOT EXISTS test_persistence (
            id SERIAL PRIMARY KEY,
            test_data VARCHAR(100)
        );
        INSERT INTO test_persistence (test_data) VALUES ('test_value_12345');
        """
        
        # Execute SQL in database
        result = self.run_compose_command([
            'exec', '-T', 'db',
            'psql', '-U', 'postgres', '-d', 'insurance_broker_prod',
            '-c', create_sql
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Failed to create test data: {result.stderr}")
        
        # Restart the database container
        print("Restarting database container...")
        self.run_compose_command(['restart', 'db'])
        
        # Wait for database to be healthy again
        time.sleep(10)
        self.assertTrue(
            self.wait_for_service_healthy('db', timeout=60),
            "Database did not become healthy after restart"
        )
        
        # Query the data
        query_sql = "SELECT test_data FROM test_persistence WHERE test_data = 'test_value_12345';"
        result = self.run_compose_command([
            'exec', '-T', 'db',
            'psql', '-U', 'postgres', '-d', 'insurance_broker_prod',
            '-t', '-c', query_sql
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Failed to query test data: {result.stderr}")
        self.assertIn('test_value_12345', result.stdout,
                     "Data was not persisted after container restart")
        
        # Clean up
        cleanup_sql = "DROP TABLE IF EXISTS test_persistence;"
        self.run_compose_command([
            'exec', '-T', 'db',
            'psql', '-U', 'postgres', '-d', 'insurance_broker_prod',
            '-c', cleanup_sql
        ], check=False)
        
        print("PostgreSQL data persisted successfully after restart")
    
    def test_redis_data_persists_after_restart(self):
        """
        Test that Redis data persists after container restart.
        **Property 1: Персистентность данных при перезапуске контейнеров**
        """
        print("\nTesting Redis data persistence...")
        
        # Set a test key in Redis
        test_key = 'test_persistence_key'
        test_value = 'test_persistence_value_12345'
        
        result = self.run_compose_command([
            'exec', '-T', 'redis',
            'redis-cli', 'SET', test_key, test_value
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Failed to set Redis key: {result.stderr}")
        
        # Force Redis to save to disk
        self.run_compose_command([
            'exec', '-T', 'redis',
            'redis-cli', 'SAVE'
        ], check=False)
        
        # Restart Redis container
        print("Restarting Redis container...")
        self.run_compose_command(['restart', 'redis'])
        
        # Wait for Redis to be healthy again
        time.sleep(5)
        self.assertTrue(
            self.wait_for_service_healthy('redis', timeout=60),
            "Redis did not become healthy after restart"
        )
        
        # Query the key
        result = self.run_compose_command([
            'exec', '-T', 'redis',
            'redis-cli', 'GET', test_key
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Failed to get Redis key: {result.stderr}")
        self.assertIn(test_value, result.stdout,
                     "Redis data was not persisted after container restart")
        
        # Clean up
        self.run_compose_command([
            'exec', '-T', 'redis',
            'redis-cli', 'DEL', test_key
        ], check=False)
        
        print("Redis data persisted successfully after restart")
    
    def test_static_files_persist_after_web_restart(self):
        """
        Test that static files persist after web container restart.
        **Property 1: Персистентность данных при перезапуске контейнеров**
        """
        print("\nTesting static files persistence...")
        
        # Collect static files
        self.run_compose_command([
            'exec', '-T', 'web',
            'python', 'manage.py', 'collectstatic', '--noinput'
        ], check=False)
        
        # Verify static file exists
        result = subprocess.run(
            ['curl', '-f', '-s', '-o', '/dev/null', '-w', '%{http_code}',
             'http://localhost:80/static/admin/css/base.css'],
            capture_output=True,
            text=True,
            check=False
        )
        self.assertEqual(result.stdout, '200', "Static file not found before restart")
        
        # Restart web container
        print("Restarting web container...")
        self.run_compose_command(['restart', 'web'])
        
        # Wait for web to be healthy again
        time.sleep(10)
        self.assertTrue(
            self.wait_for_service_healthy('web', timeout=120),
            "Web service did not become healthy after restart"
        )
        
        # Verify static file still exists
        result = subprocess.run(
            ['curl', '-f', '-s', '-o', '/dev/null', '-w', '%{http_code}',
             'http://localhost:80/static/admin/css/base.css'],
            capture_output=True,
            text=True,
            check=False
        )
        
        self.assertEqual(result.stdout, '200',
                        "Static files were not persisted after web container restart")
        
        print("Static files persisted successfully after restart")


class TestAutoRestart(DockerComposeTestCase):
    """
    Test automatic restart of failed containers.
    **Property 4: Автоматический перезапуск упавших контейнеров**
    **Validates: Требования 7.4, 8.3**
    """
    
    def test_container_auto_restarts_after_stop(self):
        """
        Test that containers automatically restart after being stopped.
        **Property 4: Автоматический перезапуск упавших контейнеров**
        """
        print("\nTesting automatic container restart...")
        
        # Choose a non-critical service to test (celery_beat)
        test_service = 'celery_beat'
        
        # Get initial container ID
        initial_container_id = self.get_container_id(test_service)
        self.assertTrue(initial_container_id, f"Could not find {test_service} container")
        
        # Stop the container (simulating a crash)
        print(f"Stopping {test_service} container...")
        subprocess.run(
            ['docker', 'stop', initial_container_id],
            capture_output=True,
            check=False
        )
        
        # Wait a bit for Docker to detect and restart
        print("Waiting for automatic restart...")
        time.sleep(15)
        
        # Check if container is running again
        status = self.get_container_status(test_service)
        self.assertEqual(status, 'running',
                        f"Container {test_service} did not auto-restart (status: {status})")
        
        # Verify it's a new container (or restarted)
        new_container_id = self.get_container_id(test_service)
        self.assertTrue(new_container_id, f"Could not find {test_service} container after restart")
        
        print(f"Container {test_service} automatically restarted successfully")
    
    def test_celery_worker_auto_restarts(self):
        """
        Test that Celery worker automatically restarts after failure.
        **Property 4: Автоматический перезапуск упавших контейнеров**
        """
        print("\nTesting Celery worker automatic restart...")
        
        test_service = 'celery_worker'
        
        # Get initial container ID
        initial_container_id = self.get_container_id(test_service)
        self.assertTrue(initial_container_id, f"Could not find {test_service} container")
        
        # Kill the container (simulating a crash)
        print(f"Killing {test_service} container...")
        subprocess.run(
            ['docker', 'kill', initial_container_id],
            capture_output=True,
            check=False
        )
        
        # Wait for automatic restart
        print("Waiting for automatic restart...")
        time.sleep(20)
        
        # Check if container is running and healthy again
        self.assertTrue(
            self.wait_for_service_healthy(test_service, timeout=60),
            f"Container {test_service} did not auto-restart and become healthy"
        )
        
        # Verify Celery worker is functional
        result = self.run_compose_command([
            'exec', '-T', test_service,
            'celery', '-A', 'config', 'inspect', 'ping'
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Celery worker is not functional after restart: {result.stderr}")
        
        print(f"Container {test_service} automatically restarted and is functional")


class TestLogging(DockerComposeTestCase):
    """
    Test logging functionality and Docker log capture.
    **Validates: Требования 8.1, 8.2**
    """
    
    def test_docker_captures_application_logs(self):
        """
        Test that Docker captures application logs and makes them accessible via docker logs.
        **Validates: Требования 8.1**
        """
        print("\nTesting Docker log capture...")
        
        # Wait for web service to be healthy
        self.assertTrue(
            self.wait_for_service_healthy('web', timeout=120),
            "Web service did not become healthy"
        )
        
        # Generate a log entry by making a request to the application
        # This will generate access logs
        subprocess.run(
            ['curl', '-s', 'http://localhost:80/admin/login/'],
            capture_output=True,
            check=False
        )
        
        # Wait a moment for logs to be written
        time.sleep(2)
        
        # Retrieve logs from web container
        result = self.run_compose_command([
            'logs', '--tail', '100', 'web'
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Failed to retrieve logs: {result.stderr}")
        
        # Verify logs are not empty
        self.assertTrue(result.stdout.strip(),
                       "Docker logs are empty - logs not being captured")
        
        # Verify logs contain expected Django/Gunicorn output
        # Look for typical Django startup or request handling messages
        log_content = result.stdout.lower()
        
        # Check for signs of Django application running
        has_django_content = any([
            'django' in log_content,
            'gunicorn' in log_content,
            'starting' in log_content,
            'spawned' in log_content,
            'listening' in log_content,
            'get /admin' in log_content,
            'post /' in log_content
        ])
        
        self.assertTrue(has_django_content,
                       "Logs do not contain expected Django/Gunicorn content")
        
        print("Docker successfully captures application logs")
    
    def test_application_logs_errors_with_traceback(self):
        """
        Test that application logs errors with full traceback.
        **Validates: Требования 8.2**
        """
        print("\nTesting error logging with traceback...")
        
        # Wait for web service to be healthy
        self.assertTrue(
            self.wait_for_service_healthy('web', timeout=120),
            "Web service did not become healthy"
        )
        
        # Trigger an error by accessing a non-existent URL
        # This should generate a 404 or similar error in logs
        subprocess.run(
            ['curl', '-s', 'http://localhost:80/nonexistent-url-that-should-404/'],
            capture_output=True,
            check=False
        )
        
        # Also try to trigger a more serious error by accessing an invalid endpoint
        subprocess.run(
            ['curl', '-s', '-X', 'POST', 'http://localhost:80/admin/'],
            capture_output=True,
            check=False
        )
        
        # Wait for logs to be written
        time.sleep(2)
        
        # Retrieve logs from web container
        result = self.run_compose_command([
            'logs', '--tail', '200', 'web'
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Failed to retrieve logs: {result.stderr}")
        
        # Verify logs contain error information
        log_content = result.stdout
        
        # Check that logs are being captured (not empty)
        self.assertTrue(log_content.strip(),
                       "No logs captured from web container")
        
        # For a more robust test, let's trigger a Python error by executing code
        # that will definitely cause an exception
        print("Triggering a Python exception to test traceback logging...")
        
        # Create a temporary management command that will raise an exception
        test_command = """
import sys
import traceback
try:
    raise ValueError("Test error for logging validation - this is expected")
except Exception as e:
    # Log the error with traceback
    import logging
    logger = logging.getLogger('django')
    logger.error("Test error occurred", exc_info=True)
    # Also print to stderr so it gets captured
    traceback.print_exc()
    sys.exit(0)  # Exit successfully since this is a test
"""
        
        # Execute Python code in the container that will log an error
        result = self.run_compose_command([
            'exec', '-T', 'web',
            'python', '-c', test_command
        ], check=False)
        
        # Wait for logs to be written
        time.sleep(2)
        
        # Retrieve logs again
        result = self.run_compose_command([
            'logs', '--tail', '100', 'web'
        ], check=False)
        
        log_content = result.stdout
        
        # Verify traceback elements are present in logs
        # Look for typical Python traceback indicators
        has_traceback = any([
            'Traceback' in log_content,
            'traceback' in log_content.lower(),
            'ValueError' in log_content,
            'Test error for logging validation' in log_content,
            'File ' in log_content and 'line' in log_content.lower()
        ])
        
        self.assertTrue(has_traceback,
                       "Logs do not contain traceback information for errors")
        
        print("Application successfully logs errors with traceback")
    
    def test_celery_logs_are_captured(self):
        """
        Test that Celery worker logs are captured by Docker.
        **Validates: Требования 8.1**
        """
        print("\nTesting Celery log capture...")
        
        # Wait for Celery worker to be healthy
        self.assertTrue(
            self.wait_for_service_healthy('celery_worker', timeout=120),
            "Celery worker did not become healthy"
        )
        
        # Retrieve logs from celery_worker container
        result = self.run_compose_command([
            'logs', '--tail', '100', 'celery_worker'
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Failed to retrieve Celery logs: {result.stderr}")
        
        # Verify logs are not empty
        self.assertTrue(result.stdout.strip(),
                       "Celery logs are empty - logs not being captured")
        
        # Verify logs contain expected Celery output
        log_content = result.stdout.lower()
        
        has_celery_content = any([
            'celery' in log_content,
            'worker' in log_content,
            'ready' in log_content,
            'connected' in log_content
        ])
        
        self.assertTrue(has_celery_content,
                       "Celery logs do not contain expected content")
        
        print("Docker successfully captures Celery logs")
    
    def test_nginx_logs_are_captured(self):
        """
        Test that Nginx access and error logs are captured by Docker.
        **Validates: Требования 8.1**
        """
        print("\nTesting Nginx log capture...")
        
        # Wait for Nginx to be healthy
        self.assertTrue(
            self.wait_for_service_healthy('nginx', timeout=60),
            "Nginx did not become healthy"
        )
        
        # Generate some access logs by making requests
        for _ in range(3):
            subprocess.run(
                ['curl', '-s', 'http://localhost:80/admin/login/'],
                capture_output=True,
                check=False
            )
        
        # Wait for logs to be written
        time.sleep(2)
        
        # Retrieve logs from nginx container
        result = self.run_compose_command([
            'logs', '--tail', '100', 'nginx'
        ], check=False)
        
        self.assertEqual(result.returncode, 0,
                        f"Failed to retrieve Nginx logs: {result.stderr}")
        
        # Verify logs are not empty
        self.assertTrue(result.stdout.strip(),
                       "Nginx logs are empty - logs not being captured")
        
        # Verify logs contain HTTP access information
        log_content = result.stdout
        
        # Look for typical Nginx access log patterns
        has_access_logs = any([
            'GET /admin' in log_content,
            'GET' in log_content and '/admin' in log_content,
            '200' in log_content or '302' in log_content,
            'HTTP' in log_content
        ])
        
        self.assertTrue(has_access_logs,
                       "Nginx logs do not contain expected access log entries")
        
        print("Docker successfully captures Nginx logs")


class TestDockerCleanup(DockerComposeTestCase):
    """Clean up Docker environment after all tests."""
    
    def test_zzz_cleanup(self):
        """Clean up Docker Compose environment (runs last due to name)."""
        print("\nCleaning up Docker Compose environment...")
        
        # Stop and remove containers
        self.run_compose_command(['down', '-v'], capture_output=False, check=False)
        
        print("Cleanup completed")


if __name__ == '__main__':
    # Run tests in order
    unittest.main(verbosity=2)
