"""
Authentication and authorization module for the Real-Time Data Collection and Monitoring System.

Provides JWT token-based authentication and API key authentication.
"""

import os
import jwt
import bcrypt
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from functools import wraps

# JWT Configuration
_jwt_secret = os.getenv("JWT_SECRET_KEY")
if not _jwt_secret:
    raise ValueError(
        "JWT_SECRET_KEY environment variable is not set. "
        "Set it to a strong random secret (e.g. openssl rand -hex 32)."
    )
JWT_SECRET_KEY = _jwt_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

# API Key Configuration
API_KEYS: Dict[str, str] = {}  # In production, store in database
API_KEY_HEADER = "X-API-Key"

security = HTTPBearer()


def generate_jwt_token(user_id: str, username: str) -> str:
    """
    Generate a JWT token for a user.

    Args:
        user_id: User identifier
        username: Username

    Returns:
        JWT token string
    """
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode a JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded token payload or None if invalid
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> Dict[str, Any]:
    """
    Dependency to get current authenticated user from JWT token.

    Args:
        credentials: HTTP Bearer credentials

    Returns:
        User information from token

    Raises:
        HTTPException: If token is invalid or expired
    """
    token = credentials.credentials
    payload = verify_jwt_token(token)
    if payload is None:
        raise HTTPException(
            status_code=401, detail="Invalid or expired authentication token"
        )
    return payload


def verify_api_key(api_key: str) -> bool:
    """
    Verify an API key.

    Args:
        api_key: API key to verify

    Returns:
        True if valid, False otherwise
    """
    # In production, check against database
    return api_key in API_KEYS.values()


def get_api_key(api_key_header: Optional[str] = None) -> str:
    """
    Dependency to get and verify API key from header.

    Args:
        api_key_header: API key from X-API-Key header

    Returns:
        API key string

    Raises:
        HTTPException: If API key is missing or invalid
    """
    if api_key_header is None:
        raise HTTPException(status_code=401, detail="API key required")
    if not verify_api_key(api_key_header):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key_header


def require_auth(use_jwt: bool = True, use_api_key: bool = True):
    """
    Decorator to require authentication (JWT or API key).
    NOTE: For FastAPI endpoints, prefer using Depends(get_current_user) directly.

    Args:
        use_jwt: Allow JWT authentication
        use_api_key: Allow API key authentication

    Returns:
        Decorator function
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # This decorator requires the 'request' kwarg to be present.
            request = kwargs.get("request")

            if request is not None:
                # Check JWT Bearer token
                if use_jwt:
                    auth_header = request.headers.get("Authorization", "")
                    if auth_header.startswith("Bearer "):
                        token = auth_header[7:]
                        payload = verify_jwt_token(token)
                        if payload is not None:
                            kwargs["current_user"] = payload
                            return await func(*args, **kwargs)

                # Check API key header
                if use_api_key:
                    api_key = request.headers.get("X-API-Key", "")
                    if api_key and verify_api_key(api_key):
                        return await func(*args, **kwargs)

            raise HTTPException(status_code=401, detail="Authentication required")

        return wrapper

    return decorator


def create_api_key(name: str) -> str:
    """
    Create a new API key.

    Args:
        name: Name/identifier for the API key

    Returns:
        Generated API key
    """
    api_key = secrets.token_urlsafe(32)
    API_KEYS[name] = api_key
    return api_key


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt with a random salt.

    Args:
        password: Plain text password

    Returns:
        bcrypt hash string
    """
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against a bcrypt hash using constant-time comparison.

    Args:
        password: Plain text password
        hashed: bcrypt hash string

    Returns:
        True if password matches, False otherwise
    """
    return bcrypt.checkpw(password.encode(), hashed.encode())
