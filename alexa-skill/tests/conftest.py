import sys
import os

# Make lambda/ importable without installing anything
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))

# Shared secret used by both the auth proxy and the skill Lambda
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-production")
