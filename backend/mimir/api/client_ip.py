"""
Client address of a request.
"""

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """Address of the client.

    Behind the nginx proxy, uvicorn runs with --proxy-headers and sets
    request.client from the X-Forwarded-For header nginx writes, so the
    request headers themselves are never trusted here.
    """
    return request.client.host if request.client else "unknown"
