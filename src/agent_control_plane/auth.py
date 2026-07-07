"""Authentication module for Agent Control Plane.

Provides API key auth for CLI/API access and session
cookie auth for the dashboard. Uses stdlib only.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agent_control_plane.inventory import (
    check_single_user_mode,
    get_connection,
    get_user,
    get_user_by_email,
    list_users,
    upsert_user,
)
from agent_control_plane.models import User, UserRole

# Session configuration
_SESSION_SECRET: str = ""
_SESSION_DURATION = 86400  # 24 hours


def _get_secret() -> str:
    """Get or create a session secret for HMAC signing."""
    global _SESSION_SECRET
    if not _SESSION_SECRET:
        _SESSION_SECRET = secrets.token_hex(32)
    return _SESSION_SECRET


# ---------------------------------------------------------------------------
# API Key Management
# ---------------------------------------------------------------------------


def generate_api_key() -> str:
    """Generate a random API key."""
    return f"acp_{secrets.token_hex(32)}"


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage using SHA-256."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(api_key: str, stored_hash: str) -> bool:
    """Verify an API key against its stored hash.

    Uses hmac.compare_digest for constant-time comparison.
    """
    computed = hash_api_key(api_key)
    return hmac.compare_digest(computed, stored_hash)


def create_user_with_key(
    name: str,
    email: str,
    role: str = "viewer",
) -> tuple[User, str]:
    """Create a new user with a generated API key.

    Returns:
        Tuple of (User, plaintext_api_key).
        The plaintext key is shown once and cannot be retrieved later.
    """
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)

    user = User(
        name=name,
        email=email,
        role=UserRole(role),
        api_key_hash=key_hash,
        created_at=datetime.now(timezone.utc),
    )

    conn = get_connection()
    try:
        upsert_user(conn, user)
        return user, api_key
    finally:
        conn.close()


def authenticate_api_key(api_key: str) -> User | None:
    """Authenticate a user by API key.

    Returns the User if valid, None otherwise.
    In single-user mode (no users exist), returns a guest admin user.
    """
    conn = get_connection()
    try:
        # Single-user mode: no auth required
        if check_single_user_mode(conn):
            return User(
                name="admin",
                email="admin@local",
                role=UserRole.ADMIN,
                api_key_hash="",
            )

        # Check against all users
        key_hash = hash_api_key(api_key)
        for user in list_users(conn):
            if user.api_key_hash and hmac.compare_digest(key_hash, user.api_key_hash):
                return user
        return None
    finally:
        conn.close()


def authenticate_email(email: str, api_key: str) -> User | None:
    """Authenticate a user by email + API key (dashboard login).

    Returns the User if valid, None otherwise.
    """
    conn = get_connection()
    try:
        if check_single_user_mode(conn):
            return User(
                name="admin",
                email="admin@local",
                role=UserRole.ADMIN,
                api_key_hash="",
            )

        user = get_user_by_email(conn, email)
        if user is None:
            return None
        if verify_api_key(api_key, user.api_key_hash):
            return user
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session Management (Dashboard)
# ---------------------------------------------------------------------------


def create_session(user_name: str) -> str:
    """Create a signed session cookie token.

    Format: timestamp.username.signature  (HMAC-SHA256)
    """
    secret = _get_secret()
    timestamp = int(time.time())
    payload = f"{timestamp}.{user_name}"
    signature = hmac.new(
        secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:16]
    return f"{payload}.{signature}"


def validate_session(token: str) -> str | None:
    """Validate a session token and return the user name.

    Returns user name if valid, None if expired or tampered.
    """
    secret = _get_secret()
    parts = token.split(".")
    if len(parts) != 3:
        return None

    timestamp_str, user_name, signature = parts
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        return None

    # Check expiration
    if time.time() - timestamp > _SESSION_DURATION:
        return None

    # Verify signature
    payload = f"{timestamp_str}.{user_name}"
    expected = hmac.new(
        secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:16]
    if not hmac.compare_digest(signature, expected):
        return None

    return user_name


def get_session_user(token: str) -> User | None:
    """Get the User from a session token.

    Returns None if the session is invalid/expired or user doesn't exist.
    """
    user_name = validate_session(token)
    if user_name is None:
        return None

    conn = get_connection()
    try:
        user = get_user(conn, user_name)
        if user is None:
            # In single-user mode, return guest admin
            if check_single_user_mode(conn):
                return User(
                    name="admin",
                    email="admin@local",
                    role=UserRole.ADMIN,
                    api_key_hash="",
                )
        return user
    finally:
        conn.close()
