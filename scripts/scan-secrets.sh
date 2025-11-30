#!/bin/bash
# Script to scan the codebase for potential secrets

set -e

echo "=========================================="
echo "Scanning codebase for secrets"
echo "=========================================="
echo ""

# Check if detect-secrets is installed
if ! command -v detect-secrets &> /dev/null; then
    echo "detect-secrets is not installed. Installing..."
    pip install detect-secrets
fi

# Run detect-secrets scan
echo "Running detect-secrets scan..."
echo ""

if [ -f .secrets.baseline ]; then
    echo "Using existing baseline file..."
    detect-secrets scan --baseline .secrets.baseline

    echo ""
    echo "Auditing detected secrets..."
    detect-secrets audit .secrets.baseline
else
    echo "No baseline file found. Creating new baseline..."
    detect-secrets scan --baseline .secrets.baseline

    echo ""
    echo "Baseline created. Review findings with:"
    echo "  detect-secrets audit .secrets.baseline"
fi

echo ""
echo "=========================================="
echo "Scan complete!"
echo "=========================================="
echo ""
echo "To review findings: detect-secrets audit .secrets.baseline"
echo "To update baseline: detect-secrets scan --baseline .secrets.baseline"
echo ""
