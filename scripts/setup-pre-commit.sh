#!/bin/bash
# Script to set up pre-commit hooks for secret detection

set -e

echo "=========================================="
echo "Setting up pre-commit hooks"
echo "=========================================="
echo ""

# Check if pre-commit is installed
if ! command -v pre-commit &> /dev/null; then
    echo "pre-commit is not installed. Installing..."
    pip install pre-commit
else
    echo "✓ pre-commit is already installed"
fi

# Install the pre-commit hooks
echo ""
echo "Installing pre-commit hooks..."
pre-commit install

# Generate secrets baseline
echo ""
echo "Generating secrets baseline..."
if [ -f .secrets.baseline ]; then
    echo "⚠ .secrets.baseline already exists. Backing up to .secrets.baseline.bak"
    cp .secrets.baseline .secrets.baseline.bak
fi

# Run detect-secrets to create baseline
detect-secrets scan --baseline .secrets.baseline

echo ""
echo "=========================================="
echo "✓ Pre-commit hooks installed successfully!"
echo "=========================================="
echo ""
echo "The hooks will now run automatically on git commit."
echo "To run manually: pre-commit run --all-files"
echo ""
echo "To update the secrets baseline after reviewing findings:"
echo "  detect-secrets scan --baseline .secrets.baseline"
echo ""
