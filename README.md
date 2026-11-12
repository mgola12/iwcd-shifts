# iwcd-shifts

Shift-leader sign-up and coordination for the Hyper-K IWCD Super-Module assembly at J-PARC (RD Building),
June 2027 – July 2028. MIT licence.

- **Phase 1, SM pre-assembly (Jun–Dec 2027):** 1 Shift Leader (SL1) + 2 shifters per day.
- **Phase 2, preparation for installation (to Jul 2028):** Shift Leader A + Shift Leader B + 2 shifters per day.
- **Hours:** Mon–Fri, 09:00–17:00 JST. Japanese holidays and J-PARC closures are `ClosedDay` rows.

## Workflow

1. The coordinator loads the **eligible list**, confirmed outside the tool by the integration TC, IWCD group leaders, TCs and Integration Engineer: *Coordinator → Eligibility list* (CSV `email,role,eligible,note`).
2. Eligible people log in with **Hyper-K SSO** (HKDB) and mark **availability** per role: *Preferred / Available / If needed*, by clicking days or entering a date range. Only the coordinator sees other people's availability.
3. The coordinator opens **Coverage**, which shows per role and month who is available and where the gaps are, and assigns single days or whole blocks. The preview warns about:
   - blocks shorter than 5 days;
   - a missing SLA 2-day overlap;
   - days already filled;
   - days the person didn't mark as available.
4. Assigned people get an email, then reminders 7 days and 1 day before each shift. Withdrawing emails the coordinator.
5. **Shifters** are imported read-only from the Hyper-K central scheduler CSV (`date,name,email,note`).

## Flags

| Flag | Fills the slot? | In yearly totals |
|---|---|---|
| none | yes | counted |
| `cover` (coordinator covers a gap) | yes | counted, also shown as "of which cover" |
| `overlap` (incoming SLA, first 2 days) | no (extra person) | listed separately |
| `onboarding` (new SL1/SLB's first 2 shifts, alongside the coordinator) | no | listed separately |

For onboarding, assign the coordinator normally on those days and mark the new person's first two days `onboarding`.

## Local development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # set DEBUG=True, SAML_ENABLED=False,
                        # EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend,
                        # BASE_URL=http://localhost:8000, DATABASE_URL=sqlite:///data/db.sqlite3
python manage.py makemigrations shifts && python manage.py migrate
python manage.py seed_iwcd && python manage.py createsuperuser
python manage.py runserver
python manage.py test shifts
```

With `SAML_ENABLED=False`, sign in with the email link (it prints to the console) or through `/admin/`.

## SSO details

| Item | Value |
|---|---|
| SP entityID | `https://iwcd-shifts.hyperk.ca/saml/metadata/` |
| ACS | `/saml/acs/` (HTTP-POST) |
| SLO | `/saml/sls/` (Redirect + POST) |
| IdP metadata | `https://hkdbweb.in2p3.fr/saml20-metadata.xml` |

- **Attributes**, released as `urn:oid` names: mail, givenName, sn, eduPersonPrincipalName (required); displayName and schacHomeOrganization (optional).
- **Matching:** users are matched on email. If the email changed but eduPersonPrincipalName matches, the existing account is kept.
- **Signing:** set `SAML_WANT_RESPONSE_SIGNED` / `SAML_WANT_ASSERTIONS_SIGNED` in `.env` to match what HKDB signs.

## Management commands

| Command | Purpose |
|---|---|
| `seed_iwcd` | Phases, roles, holidays. Idempotent. |
| `send_reminders [--dry-run]` | Daily via systemd timer |
| `backup_db` | Nightly; keeps 30 days |
| `fetch_idp_metadata` | Refresh the HKDB IdP metadata |

See `DEPLOY.md` for production.
