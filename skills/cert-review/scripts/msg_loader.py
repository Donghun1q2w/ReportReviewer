"""msg_loader.py — Parse Outlook .msg files into JSON-serialisable dicts.

Uses extract-msg (MAPI) and html2text (HTML→plaintext).
No OCR libraries — C1 compliant.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _decode_bytes(value: bytes | str | None) -> str:
    """Decode bytes with utf-8 → cp949 → euc-kr fallback; None → ''."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return value.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return value.decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text via html2text."""
    import html2text as _h2t  # local import keeps top-level import-free

    converter = _h2t.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0  # no wrapping
    return converter.handle(html)


def _normalise_body(raw: str) -> str:
    return raw.replace("\r\n", "\n").strip()


def load_msg(msg_path: Path) -> dict:
    """Parse a single .msg file.

    Returns:
        {
            "subject":     str,
            "from":        str | None,
            "to":          str | None,
            "date":        str | None,   # ISO if possible, else original string
            "body_text":   str,          # HTML→plaintext or raw body, normalised
            "attachments": [{"filename": str, "size_bytes": int}]
        }
    """
    import extract_msg  # local import — not a forbidden library

    try:
        with extract_msg.openMsg(str(msg_path)) as msg:
            # ── subject ──────────────────────────────────────────────────────
            subject = _decode_bytes(msg.subject) if msg.subject is not None else ""

            # ── sender ───────────────────────────────────────────────────────
            try:
                sender = _decode_bytes(msg.sender) if msg.sender is not None else None
            except Exception:
                sender = None

            # ── to ───────────────────────────────────────────────────────────
            try:
                to_val = _decode_bytes(msg.to) if msg.to is not None else None
            except Exception:
                to_val = None

            # ── date ─────────────────────────────────────────────────────────
            try:
                date_val = msg.date  # may be datetime or str
                if date_val is None:
                    date_str = None
                elif hasattr(date_val, "isoformat"):
                    date_str = date_val.isoformat()
                else:
                    date_str = _decode_bytes(date_val)
            except Exception:
                date_str = None

            # ── body ─────────────────────────────────────────────────────────
            try:
                html_body = msg.htmlBody  # bytes or None
                html_str = _decode_bytes(html_body) if html_body else ""
            except Exception:
                html_str = ""

            if html_str.strip():
                try:
                    body_text = _normalise_body(_html_to_text(html_str))
                except Exception:
                    body_text = _normalise_body(html_str)
            else:
                try:
                    raw = msg.body
                    body_text = _normalise_body(_decode_bytes(raw) if raw is not None else "")
                except Exception:
                    body_text = ""

            # ── attachments ──────────────────────────────────────────────────
            attachments: list[dict] = []
            try:
                for att in msg.attachments:
                    try:
                        fname = _decode_bytes(att.longFilename or att.shortFilename or "")
                        data = att.data if att.data is not None else b""
                        size = len(data) if isinstance(data, (bytes, bytearray)) else 0
                        attachments.append({"filename": fname, "size_bytes": size})
                    except Exception as exc:
                        logger.debug("Skipping attachment in %s: %s", msg_path.name, exc)
            except Exception:
                pass

            return {
                "subject": subject,
                "from": sender,
                "to": to_val,
                "date": date_str,
                "body_text": body_text,
                "attachments": attachments,
            }

    except Exception as exc:
        logger.warning("Failed to parse %s: %s", msg_path, exc)
        return {
            "subject": f"[PARSE ERROR] {msg_path.name}",
            "from": None,
            "to": None,
            "date": None,
            "body_text": "",
            "attachments": [],
        }


def load_case_emails(case_id: str, work_dir: Path, cache_root: Path) -> list[dict]:
    """Scan rawdata/<case_id>/*.msg, parse each, write to cache_root/<case_id>/emails.json.

    Returns the list of parsed email dicts.
    """
    msg_dir = work_dir / "rawdata" / case_id
    results: list[dict] = []

    if msg_dir.is_dir():
        msg_files = sorted(msg_dir.glob("*.msg"))
        for msg_path in msg_files:
            logger.info("Parsing %s", msg_path.name)
            parsed = load_msg(msg_path)
            parsed["_source_file"] = msg_path.name
            results.append(parsed)
    else:
        logger.warning("rawdata dir not found: %s", msg_dir)

    # Write cache
    cache_dir = cache_root / case_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / "emails.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote %d email(s) to %s", len(results), out_path)
    return results
