"""Vercel Serverless Function entry point."""

import sys
from pathlib import Path

# Add project root directory to Python path for Vercel Serverless runtime
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.main import app  # noqa: E402

# Vercel serverless Python runtime exposes 'app'
__all__ = ["app"]
