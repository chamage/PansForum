from django.conf import settings
from django.http import HttpResponse

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "img-src 'self' data: blob:",
        "style-src 'self'",
        "script-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"


class SecurityHeadersMiddleware:
    """Adds a strict Content-Security-Policy and Permissions-Policy to every response.

    The front-end uses no inline scripts or styles, so the policy can stay strict.
    The admin is excluded because it relies on inline scripts.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.admin_prefix = "/" + settings.ADMIN_URL.lstrip("/")

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith(self.admin_prefix):
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        return response


class MaxRequestSizeMiddleware:
    """Rejects oversized request bodies before Django starts parsing/streaming them."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > settings.MAX_REQUEST_BYTES:
            return HttpResponse("Request too large.", status=413, content_type="text/plain")
        return self.get_response(request)
