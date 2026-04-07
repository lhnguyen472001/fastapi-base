"""Pluggable async email senders.

Three implementations ship in the package:

- :class:`LoggingEmailSender` — logs the message via loguru. Useful when no
  SMTP server is available.
- :class:`SmtpEmailSender` — delivers via aiosmtplib. Default in dev / test
  via the MailHog container in ``compose.yml``.
- :class:`StubEmailSender` — test-only, captures every send in memory.

All three satisfy :class:`EmailSenderProtocol`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage as MIMEEmailMessage
from typing import Protocol

import aiosmtplib
from loguru import logger


@dataclass(frozen=True)
class EmailMessage:
    """An outbound email.

    ``html_body`` is optional — when set, the SMTP sender ships the message
    as ``multipart/alternative`` so HTML-capable clients render it while
    plain-text clients still see the text version.
    """

    to: str
    subject: str
    body: str
    html_body: str | None = None


class EmailSenderProtocol(Protocol):
    """Async email sender interface."""

    async def send(self, message: EmailMessage) -> None:
        """Deliver an email message."""
        ...


class LoggingEmailSender:
    """Logs the email instead of delivering it.

    Useful when no SMTP server is available — every OTP shows up in the
    application log.
    """

    async def send(self, message: EmailMessage) -> None:
        """Log the message via loguru."""
        logger.info(
            "LoggingEmailSender - send - to={to} subject={subject!r} body={body!r}",
            to=message.to,
            subject=message.subject,
            body=message.body,
        )


@dataclass
class StubEmailSender:
    """Test-only sender — captures every message in :attr:`sent`."""

    sent: list[EmailMessage] = field(default_factory=list)

    async def send(self, message: EmailMessage) -> None:
        """Record the message for later inspection."""
        self.sent.append(message)

    def clear(self) -> None:
        """Drop all captured messages."""
        self.sent.clear()


class SmtpEmailSender:
    """Async SMTP sender backed by ``aiosmtplib``.

    Connects per-call (no connection pooling) — fine for OTP volumes and
    simpler than managing a long-lived connection across event loops.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender_name: str,
        sender_address: str,
        use_tls: bool = False,
        username: str = "",
        password: str = "",
        timeout: int = 5,
    ) -> None:
        self.host = host
        self.port = port
        self.sender_name = sender_name
        self.sender_address = sender_address
        self.use_tls = use_tls
        self.username = username
        self.password = password
        self.timeout = timeout

    async def send(self, message: EmailMessage) -> None:
        """Build a MIME message and ship it via SMTP.

        Raises:
            RuntimeError: If aiosmtplib could not deliver the message. Callers
                that don't want a delivery failure to abort their flow should
                wrap this in their own try/except (see
                ``AuthService._issue_and_send_otp``).
        """
        mime = MIMEEmailMessage()
        mime["From"] = f"{self.sender_name} <{self.sender_address}>"
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.body)
        if message.html_body is not None:
            mime.add_alternative(message.html_body, subtype="html")

        try:
            await aiosmtplib.send(
                mime,
                hostname=self.host,
                port=self.port,
                use_tls=self.use_tls,
                username=self.username or None,
                password=self.password or None,
                timeout=self.timeout,
            )
        except aiosmtplib.SMTPException as exc:
            logger.error(
                "SmtpEmailSender - send - delivery failed: to={to} err={err}",
                to=message.to,
                err=exc,
            )
            raise RuntimeError(f"SMTP delivery failed: {exc}") from exc
