"""Security headers middleware."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # ACCEPTED RISK: 'unsafe-inline' and 'unsafe-eval' are required here.
        # - 'unsafe-eval': Tailwind CSS CDN generates styles at runtime via eval(); removing
        #   it would require switching to a build step (pre-compiled Tailwind).
        # - 'unsafe-inline': templates use inline Alpine.js x-data directives and event
        #   handlers; removing it would require adding per-request nonces to every template.
        # Accepted because the app is gated behind Cloudflare Access authentication, so XSS
        # is only exploitable by an already-authenticated user. Revisit if auth model changes
        # or if Tailwind is replaced with a compiled build.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.tailwindcss.com "
            "https://cdn.jsdelivr.net "
            "https://unpkg.com "
            "https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' "
            "https://cdn.tailwindcss.com "
            "https://cdnjs.cloudflare.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

        return response
