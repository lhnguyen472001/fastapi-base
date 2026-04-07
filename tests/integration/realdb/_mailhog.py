"""Tiny async MailHog HTTP API client used by the realdb email tests."""

from __future__ import annotations

import base64
import quopri
import re
import socket

import httpx

MAILHOG_BASE_URL = "http://localhost:8025"
_OTP_PATTERN = re.compile(r"\b(\d{6})\b")


def is_reachable(host: str = "localhost", port: int = 8025, timeout: float = 0.5) -> bool:
    """Cheap TCP probe so tests can skip cleanly when MailHog isn't running."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


class MailHogClient:
    """Async wrapper around the MailHog v1 / v2 HTTP API."""

    def __init__(self, base_url: str = MAILHOG_BASE_URL) -> None:
        self.base_url = base_url

    async def clear_inbox(self) -> None:
        """Delete every message in MailHog's inbox."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
            await client.delete("/api/v1/messages")

    async def all_messages(self) -> list[dict]:
        """Return MailHog's full inbox as a list of message dicts."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
            response = await client.get("/api/v2/messages")
            response.raise_for_status()
            payload = response.json()
            return payload.get("items", [])

    async def latest_for(self, recipient: str) -> dict | None:
        """Return the most recent message addressed to ``recipient``, if any."""
        for item in await self.all_messages():
            for to in item.get("To", []):
                mailbox = to.get("Mailbox", "")
                domain = to.get("Domain", "")
                if f"{mailbox}@{domain}".lower() == recipient.lower():
                    return item
        return None

    async def find_otp_for(self, recipient: str) -> str | None:
        """Extract a 6-digit OTP from the latest message addressed to ``recipient``.

        For multipart emails ``Content.Body`` contains the full MIME envelope
        including boundaries and headers — searching that directly produces
        false positives. We always extract from the ``text/plain`` MIME part
        when one is available, and fall back to the raw body otherwise.
        """
        message = await self.latest_for(recipient)
        if message is None:
            return None

        plain_body = self._plain_part_body(message)
        if plain_body is None:
            plain_body = message.get("Content", {}).get("Body", "")

        match = _OTP_PATTERN.search(plain_body)
        return match.group(1) if match else None

    @classmethod
    def _plain_part_body(cls, message: dict) -> str | None:
        """Return the decoded body of the ``text/plain`` MIME part, if any."""
        parts = (message.get("MIME") or {}).get("Parts") or []
        for part in parts:
            headers = part.get("Headers", {})
            content_type_values = headers.get("Content-Type", [])
            if any("text/plain" in v for v in content_type_values):
                return cls._decode_part(part)
        return None

    @staticmethod
    def _decode_part(part: dict) -> str:
        """Decode a MIME part body honouring its Content-Transfer-Encoding."""
        body = part.get("Body", "")
        encodings = part.get("Headers", {}).get("Content-Transfer-Encoding", [])
        encoding = encodings[0].lower() if encodings else ""
        if encoding == "quoted-printable":
            return quopri.decodestring(body).decode("utf-8", errors="replace")
        if encoding == "base64":
            return base64.b64decode(body).decode("utf-8", errors="replace")
        return body

    async def latest_html_for(self, recipient: str) -> str | None:
        """Return the decoded HTML alternative body of the latest message."""
        message = await self.latest_for(recipient)
        if message is None:
            return None
        parts = (message.get("MIME") or {}).get("Parts") or []
        for part in parts:
            headers = part.get("Headers", {})
            content_type_values = headers.get("Content-Type", [])
            if any("text/html" in v for v in content_type_values):
                return self._decode_part(part)
        return None
