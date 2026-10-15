from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Browser-side hardening applied to every response.

    Framing is refused outright: the consent page's "Allow" button must never
    be clickable inside someone else's invisible iframe (clickjacking). The
    popup widget opens a window, not a frame, so it's unaffected.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.scheme == "https":
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response
