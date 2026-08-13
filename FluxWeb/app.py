"""WSGI entrypoint.

The application itself lives in the ``fluxweb`` package; this module exists so
existing deployment configuration (``vercel.json`` points at ``app.py``) and
``flask run`` keep working unchanged.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from fluxweb import create_app  # noqa: E402 - must follow load_dotenv()

app = create_app()


if __name__ == "__main__":
    # Debug is off unless explicitly requested. The Werkzeug debugger is a
    # remote code execution surface, so it must never default on (audit M-31).
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "27003"))
    app.run(debug=debug, host=host, port=port)
