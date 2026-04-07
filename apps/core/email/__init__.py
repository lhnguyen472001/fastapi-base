"""Email sender abstraction + Jinja-based template renderer."""

from .renderer import EmailRenderer
from .sender import (
    EmailMessage,
    EmailSenderProtocol,
    LoggingEmailSender,
    SmtpEmailSender,
    StubEmailSender,
)

__all__ = [
    "EmailMessage",
    "EmailRenderer",
    "EmailSenderProtocol",
    "LoggingEmailSender",
    "SmtpEmailSender",
    "StubEmailSender",
]
