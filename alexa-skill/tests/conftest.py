import sys
import os

# Make lambda/ importable without installing anything
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))

# Provide dummy credentials so handler can be imported without real env vars
os.environ.setdefault("SOMFY_USER", "test@example.com")
os.environ.setdefault("SOMFY_PASS", "testpass")
