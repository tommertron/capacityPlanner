#!/usr/bin/env python3
"""Diagnostic script to check dependencies and imports."""

import sys
import subprocess

print("=== Python Environment ===")
print(f"Python version: {sys.version}")
print(f"Python executable: {sys.executable}")
print()

print("=== Installed Packages ===")
try:
    result = subprocess.run([sys.executable, "-m", "pip", "list"],
                          capture_output=True, text=True)
    print(result.stdout)
except Exception as e:
    print(f"Error listing packages: {e}")
print()

print("=== Testing Core Imports ===")
required_modules = [
    "pandas",
    "dateutil",
    "flask",
]

for module in required_modules:
    try:
        __import__(module)
        print(f"✓ {module} - OK")
    except ImportError as e:
        print(f"✗ {module} - MISSING: {e}")
print()

print("=== Testing Project Imports ===")
try:
    from capacity_tracker import main
    print("✓ capacity_tracker.main - OK")
except ImportError as e:
    print(f"✗ capacity_tracker.main - FAILED: {e}")
    import traceback
    traceback.print_exc()
print()

print("=== Checking for PuLP ===")
try:
    import pulp
    print(f"⚠ PuLP IS installed: {pulp.__version__}")
    print("   This is unexpected - the project doesn't use PuLP")
except ImportError:
    print("✓ PuLP not installed (expected)")
