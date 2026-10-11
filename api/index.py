"""Vercel serverless entry point.

Vercel's Python runtime looks for a WSGI callable named `app` in a file under
`api/`. This re-exports the Flask app from the package.

Note: on Vercel the filesystem is ephemeral (only /tmp is writable), so the
knowledge base does not persist between invocations unless an external database
is used behind `FactStore`.
"""

import os
import sys

# Make the project root importable inside the serverless function.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tera.webapp import app  # noqa: E402  (WSGI callable Vercel expects)

__all__ = ["app"]
