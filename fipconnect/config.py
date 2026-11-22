"""Settings read from the environment, plus .env and secret-key helpers."""

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTANCE = ROOT / "instance"
SECRET_FILE = INSTANCE / "secret.key"


def load_env_file(path):
    """Load KEY=VALUE lines from a .env file without overriding variables
    that are already set in the environment."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def database_url(raw):
    """Return a SQLAlchemy URL that uses the psycopg 3 driver."""
    value = (raw or "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is not set. Add it to .env (see .env.example).")
    for prefix in ("postgres://", "postgresql://"):
        if value.startswith(prefix):
            return "postgresql+psycopg://" + value[len(prefix):]
    return value


def load_or_create_secret():
    INSTANCE.mkdir(parents=True, exist_ok=True)
    try:
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        secret = secrets.token_hex(32)
        try:
            SECRET_FILE.write_text(secret, encoding="utf-8")
        except OSError:
            return secret
        return secret


def _int_env(name, default):
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def settings_from_environment():
    return {
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "MAX_CONTENT_LENGTH": 1_000_000,
        "FACE_SERVICE_URL": os.environ.get(
            "FIPCONNECT_FACE_SERVICE_URL", "http://127.0.0.1:5018"
        ),
        "ADMIN_HOST": os.environ.get("FIP_ADMIN_HOST", "admin.localhost"),
        "CLIENT_URL": os.environ.get("FIP_CLIENT_URL", "http://localhost:5000"),
        "ALLOW_SETUP": os.environ.get("FIP_ALLOW_SETUP", "").strip().lower()
        in {"1", "true", "yes", "on"},
        "MIN_LEAD_DAYS": _int_env("FIP_MIN_LEAD_DAYS", 7),
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "pool_pre_ping": True,
            "connect_args": {"connect_timeout": 10},
        },
    }
