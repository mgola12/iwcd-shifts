from django.conf import settings
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "IWCD Shifts admin"
admin.site.site_title = "IWCD Shifts"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("shifts.urls")),
]

if settings.SAML_ENABLED:
    from djangosaml2 import views as saml_views

    urlpatterns += [
        # SLO endpoint registered with the IdP (/saml/sls/); djangosaml2's own
        # routes (login/, acs/, metadata/, ls/ ...) are included below.
        path("saml/sls/", saml_views.LogoutView.as_view(), name="saml2_sls"),
        path("saml/", include("djangosaml2.urls")),
    ]
