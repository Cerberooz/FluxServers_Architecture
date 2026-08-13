"""Flask extension singletons.

Kept in their own module so models, services, and blueprints can import them
without importing the application factory (which would be circular).
"""

from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

# Default limits are deliberately generous; the sensitive endpoints declare
# their own much stricter limits (audit H-10).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["600 per hour"],
    headers_enabled=True,
)
