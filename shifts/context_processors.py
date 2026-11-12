from django.conf import settings


def site(request):
    return {
        "SAML_ENABLED": settings.SAML_ENABLED,
        "MAGIC_LINK_ENABLED": settings.MAGIC_LINK_ENABLED,
        "SHIFT_START": settings.SHIFT_START,
        "SHIFT_END": settings.SHIFT_END,
    }
