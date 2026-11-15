from django.apps import AppConfig


class AdminUIConfig(AppConfig):
    """The Django admin, dressed as DevTrack.

    Listed before ``django.contrib.admin`` so its ``templates/admin/*`` overrides win, and it names the
    site. The look itself is ``static/devtrack_admin/admin.css`` (the same tokens as the web app's
    ``src/styles/index.css``, mapped onto the admin's CSS variables).
    """

    name = "apps.adminui"
    verbose_name = "Admin UI"

    def ready(self):
        from django.conf import settings
        from django.contrib import admin

        admin.site.site_header = "DevTrack"
        admin.site.site_title = "DevTrack admin"
        admin.site.index_title = "Overview"
        # "View site" opens the web app, not the API host.
        admin.site.site_url = settings.FRONTEND_URL
