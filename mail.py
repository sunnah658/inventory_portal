"""Send mail from the portal through the SMTP account the portal admin sets
on the Mail settings page (build 80). The settings live in the settings
table: smtp_sender (the mail address the portal sends from), smtp_password,
smtp_host (the mail server), smtp_port and smtp_encryption (starttls, ssl
or none). Nothing is sent when the settings are not filled in, and a failed
send never raises — it only returns False, so a mail problem can never
break the page that triggered it (for example, creating an application)."""

import smtplib
from email.message import EmailMessage

from models import setting_get


def smtp_config(db):
    """(sender, password, host, port, encryption) from the settings table.
    The port defaults to 465 for SSL and 587 otherwise; the encryption
    defaults to STARTTLS."""
    sender = (setting_get(db, "smtp_sender", "") or "").strip()
    password = setting_get(db, "smtp_password", "") or ""
    host = (setting_get(db, "smtp_host", "") or "").strip()
    try:
        port = int(setting_get(db, "smtp_port", "") or 0)
    except (TypeError, ValueError):
        port = 0
    encryption = (setting_get(db, "smtp_encryption", "") or "").strip().lower()
    if encryption not in ("starttls", "ssl", "none"):
        encryption = "starttls"
    if not port:
        port = 465 if encryption == "ssl" else 587
    return sender, password, host, port, encryption


def smtp_configured(db):
    """True when the portal admin has filled in the sender, its password
    and the mail server, so mail can be sent."""
    sender, password, host, port, _encryption = smtp_config(db)
    return bool(sender and password and host and port)


def send_mail(db, to_email, subject, body):
    """Send one plain-text mail from the configured sender account.
    Returns (True, "") on success, or (False, reason) when it cannot be
    sent. Never raises."""
    sender, password, host, port, encryption = smtp_config(db)
    if not (sender and password and host and port):
        return False, "Mail is not set up yet. The portal admin sets it on the Mail settings page."
    if not (to_email or "").strip():
        return False, "No email address to send to."
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email.strip()
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        if encryption == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            if encryption == "starttls":
                server.starttls()
        try:
            server.login(sender, password)
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return True, ""
    except Exception as exc:  # noqa: BLE001 - the reason is reported, not raised
        return False, str(exc)


def valid_email(address):
    """A rough check that an address looks like a mail address: one @,
    something before it and a dot after it."""
    address = (address or "").strip()
    if "@" not in address:
        return False
    local, domain = address.rsplit("@", 1)
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")
