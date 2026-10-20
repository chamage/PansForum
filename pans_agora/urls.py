from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView
from django.views.static import serve

admin.site.site_header = f"{settings.SITE_NAME} administration"
admin.site.site_title = settings.SITE_NAME

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("robots.txt", TemplateView.as_view(template_name="robots.txt", content_type="text/plain")),
    path("", include("accounts.urls")),
    path("", include("forum.urls")),
]

if settings.SERVE_MEDIA:
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]
