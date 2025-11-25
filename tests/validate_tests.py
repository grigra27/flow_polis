#!/usr/bin/env python
"""
Validation script for integration tests.
This script validates the test structure without requiring Docker.
"""
import ast
import sys
from pathlib import Path


def validate_test_file(filepath):
    """Validate the structure of a test file."""
    print(f"Validating {filepath}...")
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Parse the file
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        print(f"❌ Syntax error in {filepath}: {e}")
        return False
    
    # Find test classes
    test_classes = []
    test_methods = []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if node.name.startswith('Test'):
                test_classes.append(node.name)
                # Count test methods in this class
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name.startswith('test_'):
                        test_methods.append(f"{node.name}.{item.name}")
    
    print(f"✓ Found {len(test_classes)} test classes")
    print(f"✓ Found {len(test_methods)} test methods")
    
    # Check for required test classes
    required_classes = [
        'TestDockerContainerStartup',
        'TestDatabaseConnection',
        'TestCeleryRedisConnection',
        'TestNginxAccess',
        'TestStaticFiles',
        'TestDataPersistence',
        'TestAutoRestart',
        'TestLogging'
    ]
    
    missing_classes = []
    for required in required_classes:
        if required not in test_classes:
            missing_classes.append(required)
    
    if missing_classes:
        print(f"❌ Missing required test classes: {', '.join(missing_classes)}")
        return False
    
    print("✓ All required test classes present")
    
    # Check for property validation comments
    property_markers = [
        'Property 1: Персистентность данных при перезапуске контейнеров',
        'Property 4: Автоматический перезапуск упавших контейнеров'
    ]
    
    found_properties = []
    for marker in property_markers:
        if marker in content:
            found_properties.append(marker)
    
    print(f"✓ Found {len(found_properties)} property markers")
    
    # Check for requirement validation comments
    if 'Validates: Требования' in content:
        print("✓ Requirement validation comments present")
    else:
        print("⚠ Warning: No requirement validation comments found")
    
    return True


def main():
    """Main validation function."""
    print("=" * 60)
    print("Integration Test Validation")
    print("=" * 60)
    print()
    
    test_file = Path(__file__).parent / 'test_docker_integration.py'
    
    if not test_file.exists():
        print(f"❌ Test file not found: {test_file}")
        return 1
    
    if validate_test_file(test_file):
        print()
        print("=" * 60)
        print("✓ All validations passed!")
        print("=" * 60)
        print()
        print("To run the integration tests, you need:")
        print("  1. Docker and Docker Compose installed")
        print("  2. .env.prod and .env.prod.db configured")
        print("  3. Run: python tests/test_docker_integration.py")
        print("  Or: ./tests/run_integration_tests.sh")
        return 0
    else:
        print()
        print("=" * 60)
        print("❌ Validation failed")
        print("=" * 60)
        return 1


if __name__ == '__main__':
    sys.exit(main())
