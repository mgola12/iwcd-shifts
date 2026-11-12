"""Download the HKDB IdP metadata to SAML_DIR/idp-metadata.xml (avoids a fetch on every start)."""
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Fetch Hyper-K IdP metadata into SAML_DIR/idp-metadata.xml"

    def handle(self, *args, **o):
        url = settings.SAML_IDP_METADATA_URL
        req = urllib.request.Request(url, headers={"User-Agent": "iwcd-shifts"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if b"EntityDescriptor" not in data:
            raise CommandError("Response does not look like SAML metadata.")
        settings.SAML_DIR.mkdir(parents=True, exist_ok=True)
        settings.SAML_IDP_METADATA_FILE.write_bytes(data)
        self.stdout.write(self.style.SUCCESS(f"Saved {len(data)} bytes to {settings.SAML_IDP_METADATA_FILE}"))
