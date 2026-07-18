"""Audit middleware for sensitive actions."""

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.logging import logger


class AuditMiddleware(BaseHTTPMiddleware):
    """Audit every sensitive action."""

    SENSITIVE_ENDPOINTS = [
        "/trading/place_order", "/trading/cancel_order", "/trading/modify_order",
        "/risk/kill_switch", "/sessions/", "/admin/",
    ]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        path = request.url.path
        is_sensitive = any(path.startswith(ep) for ep in self.SENSITIVE_ENDPOINTS)
        response = await call_next(request)
        process_time = time.time() - start_time
        if is_sensitive:
            user_id = "anonymous"
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                user_id = "authenticated_user"
            logger.info(f"AUDIT: {request.method} {path}", extra={"event_type": "API_AUDIT", "user_id": user_id,
                                                                  "method": request.method, "path": path,
                                                                  "status_code": response.status_code,
                                                                  "process_time_ms": round(process_time * 1000, 2),
                                                                  "correlation_id": getattr(request.state, "correlation_id", None),
                                                                  "client_ip": request.client.host if request.client else "unknown"})
        return response
