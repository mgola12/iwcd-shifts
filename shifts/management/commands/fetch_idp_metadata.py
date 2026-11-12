"""Download the HKDB IdP metadata to SAML_DIR/idp-metadata.xml.

Run daily (systemd timer): the HKDB metadata carries validUntil ~20 days ahead, and
pysaml2 refuses expired metadata.

Known HKDB quirk (Nov 2026): the file uses the prefix 'mdattr:' without declaring its
namespace, which makes it invalid XML. We add the declaration before saving.
"""
import re
import urllib.request
import xml.etree.ElementTree as ET

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

MISSING_NS = {
    "mdattr": "urn:oasis:names:tc:SAML:metadata:attribute",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}


def repair(xml: str) -> str:
    m = re.search(r"<md:EntityDescriptor\b", xml)
    if not m:
        return xml
    for prefix, uri in MISSING_NS.items():
        if f"<{prefix}:" in xml and f"xmlns:{prefix}=" not in xml[: xml.find(">", m.start())]:
            xml = xml[: m.end()] + f' xmlns:{prefix}="{uri}"' + xml[m.end():]
    return xml


class Command(BaseCommand):
    help = "Fetch Hyper-K IdP metadata into SAML_DIR/idp-metadata.xml"

    def handle(self, *args, **o):
        url = settings.SAML_IDP_METADATA_URL
        req = urllib.request.Request(url, headers={"User-Agent": "iwcd-shifts"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8")
        if "EntityDescriptor" not in text:
            raise CommandError("Response does not look like SAML metadata.")
        fixed = repair(text)
        try:
            root = ET.fromstring(fixed.encode("utf-8"))
        except ET.ParseError as e:
            raise CommandError(f"IdP metadata is not valid XML even after repair: {e}")
        settings.SAML_DIR.mkdir(parents=True, exist_ok=True)
        settings.SAML_IDP_METADATA_FILE.write_text(fixed, encoding="utf-8")
        note = " (repaired missing namespace)" if fixed != text else ""
        self.stdout.write(self.style.SUCCESS(
            f"Saved {settings.SAML_IDP_METADATA_FILE}{note}; entityID={root.get('entityID')}, "
            f"validUntil={root.get('validUntil')}"))
