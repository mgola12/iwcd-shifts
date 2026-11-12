"""Nightly SQLite backup with 30-day retention (uses SQLite's online backup API)."""
import datetime as dt
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Copy the SQLite database to BACKUP_DIR and delete copies older than BACKUP_KEEP_DAYS."

    def handle(self, *args, **o):
        db = settings.DATABASES["default"]
        if "sqlite" not in db["ENGINE"]:
            raise CommandError("Not SQLite; use pg_dump for Postgres.")
        out_dir = settings.BACKUP_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"db-{dt.datetime.now():%Y%m%d-%H%M%S}.sqlite3"
        src = sqlite3.connect(str(db["NAME"]))
        dst = sqlite3.connect(str(target))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        cutoff = dt.datetime.now() - dt.timedelta(days=settings.BACKUP_KEEP_DAYS)
        removed = 0
        for f in out_dir.glob("db-*.sqlite3"):
            if dt.datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                removed += 1
        self.stdout.write(f"Backup written to {target}; {removed} old backup(s) removed.")
