"""
Rate limiting module for the Real-Time Data Collection and Monitoring System.

Provides rate limiting functionality to prevent abuse.
"""

import os
import time
from typing import Dict, Tuple
from collections import defaultdict
from fastapi import HTTPException, Request


class RateLimiter:
    """Simple in-memory rate limiter (use Redis in production)."""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests per window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, list] = defaultdict(list)

    def is_allowed(self, identifier: str) -> Tuple[bool, int]:
        """
        Check if request is allowed.

        Args:
            identifier: Client identifier (IP address, user ID, etc.)

        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Clean old requests
        self.requests[identifier] = [
            req_time
            for req_time in self.requests[identifier]
            if req_time > window_start
        ]

        # Check limit
        if len(self.requests[identifier]) >= self.max_requests:
            return False, 0

        # Add current request
        self.requests[identifier].append(now)

        remaining = self.max_requests - len(self.requests[identifier])
        return True, remaining

    def get_retry_after(self, identifier: str) -> int:
        """
        Seconds until the oldest request in the window expires, freeing a slot.

        Args:
            identifier: Client identifier

        Returns:
            Seconds to wait before retrying (minimum 1)
        """
        now = time.time()
        window_start = now - self.window_seconds
        timestamps = [t for t in self.requests[identifier] if t > window_start]
        if not timestamps:
            return 1
        oldest = min(timestamps)
        return max(1, int(oldest + self.window_seconds - now))

    def get_remaining(self, identifier: str) -> int:
        """
        Get remaining requests for identifier.

        Args:
            identifier: Client identifier

        Returns:
            Number of remaining requests
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Clean old requests
        self.requests[identifier] = [
            req_time
            for req_time in self.requests[identifier]
            if req_time > window_start
        ]

        return max(0, self.max_requests - len(self.requests[identifier]))


# Global rate limiter instance
rate_limiter = RateLimiter(
    max_requests=int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "100")),
    window_seconds=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
)


def get_client_identifier(request: Request) -> str:
    """
    Get client identifier from the direct TCP peer address.

    X-Forwarded-For is intentionally ignored because it is user-controlled and
    trivially spoofed, allowing a client to bypass the rate limiter.

    Args:
        request: FastAPI request object

    Returns:
        Client IP string or "unknown"
    """
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> None:
    """
    Check rate limit for request.

    Args:
        request: FastAPI request object

    Raises:
        HTTPException: If rate limit exceeded
    """
    identifier = get_client_identifier(request)
    allowed, remaining = rate_limiter.is_allowed(identifier)

    if not allowed:
        retry_after = rate_limiter.get_retry_after(identifier)
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please try again later.",
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(retry_after),
                "Retry-After": str(retry_after),
            },
        )
