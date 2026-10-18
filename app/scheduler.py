"""Bakgrundsjobb, en gång i timmen: daglig säkerhetskopia, veckobrev och tidskapseln.
En tråd räcker – appen kör med en worker. Varje jobb skyddas så att ett fel inte stoppar de andra."""
import datetime as dt
import threading
import time

from . import backup


def run_jobs(log) -> None:
    from .core import get_settings, set_settings, today
    from .digest import build_digest, digest_due
    from .routes_mail import send_to_couple
    try:
        name = backup.daily_backup(today())
        if name:
            log.info("backup_created file=%s", name)
    except Exception as e:  # noqa: BLE001 – jobbet får aldrig döda tråden
        log.error("backup_failed error=%s: %s", type(e).__name__, e)
    try:
        week = digest_due(dt.datetime.now())
        if week:
            subject, body = build_digest(get_settings().get("app_url", ""))
            n = send_to_couple(subject, body, kind="digest")
            set_settings({"digest_week": week})  # även vid fel – hellre ett missat brev än ett per timme
            log.info("digest_sent week=%s ok=%s", week, n)
    except Exception as e:  # noqa: BLE001
        log.error("digest_failed error=%s: %s", type(e).__name__, e)
    try:
        from .capsule import capsule_due, send_capsule
        if capsule_due():
            send_capsule(log)
    except Exception as e:  # noqa: BLE001
        log.error("capsule_failed error=%s: %s", type(e).__name__, e)


def start(log) -> None:
    def loop():
        while True:
            run_jobs(log)
            time.sleep(3600)

    threading.Thread(target=loop, name="jobb", daemon=True).start()
