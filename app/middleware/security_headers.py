from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Browser-side hardening applied to every response.

    Framing is refused outright: the consent page's "Allow" button must never
    be clickable inside someone else's invisible iframe (clickjacking). The
    popup widget opens a window, not a frame, so it's unaffected.

    The one exception is an embedded sign-in page (app/oidc/embed.py), which
    sets its own `frame-ancestors` naming the single origin allowed to frame
    it -- X-Frame-Options can't express that, so it is left off there.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        csp = headers.get("Content-Security-Policy", "")
        if "frame-ancestors" not in csp:
            headers["X-Frame-Options"] = "DENY"
            headers["Content-Security-Policy"] = f"{csp}; frame-ancestors 'none'" if csp else "frame-ancestors 'none'"
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.scheme == "https":
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response
