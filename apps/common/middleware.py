from django.conf import settings


class ApiResponseHeadersMiddleware:
    """Headers that only make sense for the JSON API (everything under /api/).

    * ``Cache-Control: no-store`` — authenticated JSON must never be kept by a shared cache or the
      browser's back/forward cache, where the next person on a shared machine could read it.
    * A locked-down Content-Security-Policy — the API returns JSON, so if a response were ever
      rendered as a document (a content-type mix-up, an error page) it could not load or run anything.
      Skipped in DEBUG because DRF's browsable API needs inline styles and scripts.
    """

    CSP = "default-src 'none'; frame-ancestors 'none'"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response.setdefault("Cache-Control", "no-store")
            if not settings.DEBUG:
                response.setdefault("Content-Security-Policy", self.CSP)
        return response
