from djangosaml2.backends import Saml2Backend


class HyperKSaml2Backend(Saml2Backend):
    """Hyper-K SSO (HKDB). Users are matched on lower-cased email.

    If no user has that email but one has the same eduPersonPrincipalName
    (e.g. after an institutional email change), the email is updated instead
    of creating a duplicate account.
    """

    def clean_user_main_attribute(self, main_attribute):
        return (main_attribute or "").strip().lower()

    def get_or_create_user(self, user_lookup_key, user_lookup_value, create_unknown_user,
                           idp_entityid, attributes, attribute_mapping, request):
        from .models import User

        email = (user_lookup_value or "").strip().lower()
        eppn = None
        for key in ("eduPersonPrincipalName", "urn:oid:1.3.6.1.4.1.5923.1.1.1.6"):
            if attributes.get(key):
                eppn = attributes[key][0]
                break
        if email and eppn and not User.objects.filter(email__iexact=email).exists():
            moved = User.objects.filter(eppn=eppn).first()
            if moved:
                moved.email = email
                moved.save(update_fields=["email"])
        return super().get_or_create_user(user_lookup_key, user_lookup_value, create_unknown_user,
                                          idp_entityid, attributes, attribute_mapping, request)
