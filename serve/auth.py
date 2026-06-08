"""Bearer-token auth dependency. Timing-safe comparison (it's a credit union)."""
import secrets

from fastapi import Header, HTTPException, status

from serve.config import get_settings


def require_auth(authorization: str = Header(default="")) -> None:
    token = get_settings().token
    expected = f"Bearer {token}" if token else None
    if not (expected and authorization and secrets.compare_digest(authorization, expected)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token.",
        )
