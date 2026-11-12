# Deploying iwcd-shifts on the wcte.hyperk.ca server

Target: **https://iwcd-shifts.hyperk.ca**, running next to wcte.hyperk.ca. Expected time is about 1–2 hours.
It's a small Django app (Python, SQLite, gunicorn) behind the existing nginx (or Apache).

## 0. Prerequisites

- **DNS:** `iwcd-shifts.hyperk.ca` points at this server (A record, or a CNAME to `wcte.hyperk.ca`).
- **Packages:** Python ≥ 3.10 and `xmlsec1`, which SAML uses to sign and verify:
  - Debian/Ubuntu: `sudo apt install python3-venv xmlsec1`
  - RHEL/Alma: `sudo dnf install python3 xmlsec1 xmlsec1-openssl`
- **Mail:** outgoing mail works from this host. Use the same relay as wcte.hyperk.ca, if it sends mail.

## 1. User, code, virtualenv

```bash
sudo useradd --system --home /srv/iwcd-shifts --shell /usr/sbin/nologin iwcd
sudo mkdir -p /srv/iwcd-shifts/{data,backups,saml}
sudo git clone https://github.com/<org>/iwcd-shifts.git /srv/iwcd-shifts/app   # or unzip the release
sudo python3 -m venv /srv/iwcd-shifts/venv
sudo /srv/iwcd-shifts/venv/bin/pip install -r /srv/iwcd-shifts/app/requirements.txt
sudo chown -R iwcd:iwcd /srv/iwcd-shifts
```

## 2. Configuration (`/srv/iwcd-shifts/app/.env`)

```bash
cd /srv/iwcd-shifts/app
sudo -u iwcd cp .env.example .env
sudo -u iwcd python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # paste as SECRET_KEY
sudo -u iwcd nano .env     # SECRET_KEY, EMAIL_*, DEFAULT_FROM_EMAIL, SAML_CONTACT_*
sudo chmod 600 .env
```

The paths in `.env.example` already match this layout (`/srv/iwcd-shifts/...`).

## 3. SAML keys and the HKDB metadata

```bash
cd /srv/iwcd-shifts/saml
sudo -u iwcd openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 \
     -keyout sp.key -out sp.crt -subj "/CN=iwcd-shifts.hyperk.ca"
sudo chmod 600 sp.key
cd /srv/iwcd-shifts/app
sudo -u iwcd ../venv/bin/python manage.py fetch_idp_metadata
```

- The certificate is valid for 10 years and appears in our SP metadata. **Back up `sp.key`.** If it changes, Hyper-K has to re-register the SP.
- Re-run `fetch_idp_metadata` whenever IN2P3 rotates their certificate.

## 4. Database and initial data

```bash
cd /srv/iwcd-shifts/app
sudo -u iwcd ../venv/bin/python manage.py makemigrations shifts   # first install only; then commit shifts/migrations
sudo -u iwcd ../venv/bin/python manage.py migrate
sudo -u iwcd ../venv/bin/python manage.py seed_iwcd               # phases, roles, Japanese holidays
sudo -u iwcd ../venv/bin/python manage.py createsuperuser         # Mohit's email (same as HKDB)
sudo -u iwcd ../venv/bin/python manage.py collectstatic --noinput
sudo -u iwcd ../venv/bin/python manage.py check --deploy
sudo -u iwcd DEBUG=True SECRET_KEY=x ../venv/bin/python manage.py test shifts   # all should pass
```

## 5. Services

```bash
sudo cp deploy/iwcd-shifts.service deploy/iwcd-shifts-*.service deploy/iwcd-shifts-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iwcd-shifts iwcd-shifts-reminders.timer iwcd-shifts-backup.timer
systemctl status iwcd-shifts
```

- gunicorn listens on `127.0.0.1:8010`. If that port is taken, change it in the unit file and in the proxy config.
- If systemd is older than v241 and rejects `Asia/Tokyo` in `OnCalendar`, use the server's local time instead. 08:00 JST is 15:00 PST, or 16:00 PDT in summer.

## 6. Web server and TLS

**nginx:**

```bash
sudo cp deploy/nginx-iwcd-shifts.conf /etc/nginx/sites-available/iwcd-shifts
sudo ln -s /etc/nginx/sites-available/iwcd-shifts /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d iwcd-shifts.hyperk.ca
```

**Apache:** use `deploy/apache-iwcd-shifts.conf` and run `certbot --apache -d iwcd-shifts.hyperk.ca`.

## 7. Check

| Check | Expected result |
|---|---|
| https://iwcd-shifts.hyperk.ca/ | Login page |
| https://iwcd-shifts.hyperk.ca/saml/metadata/ | XML with `entityID="https://iwcd-shifts.hyperk.ca/saml/metadata/"`. **Send this URL to Mohit.** |
| https://iwcd-shifts.hyperk.ca/admin/ | Login with the superuser |
| `sudo -u iwcd ../venv/bin/python manage.py send_reminders --dry-run` | Runs without error |
| `sudo -u iwcd ../venv/bin/python manage.py backup_db` | Creates a file in `/srv/iwcd-shifts/backups` |

## Updating

```bash
cd /srv/iwcd-shifts/app && sudo -u iwcd git pull
sudo -u iwcd ../venv/bin/pip install -r requirements.txt
sudo -u iwcd ../venv/bin/python manage.py migrate
sudo -u iwcd ../venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart iwcd-shifts
```

## Restore a backup

```bash
sudo systemctl stop iwcd-shifts
sudo -u iwcd cp /srv/iwcd-shifts/backups/db-YYYYMMDD-HHMMSS.sqlite3 /srv/iwcd-shifts/data/db.sqlite3
sudo systemctl start iwcd-shifts
```

Test a restore once a quarter.
