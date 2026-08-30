"""UTF-8 safety for the console.

The agents log progress with emoji (🔧, ✅, ⚠️). On Windows, `sys.stdout`
defaults to the legacy ANSI code page (cp1252), which cannot encode those
characters, so the *log line itself* raises UnicodeEncodeError. Inside a tool
wrapper that exception propagates and kills the tool call, and the analyst
then reports "issue with the tool responses due to encoding problems" and
falls back to writing a report with no data behind it.

Calling `ensure_utf8_console()` once at process start makes stdout/stderr
UTF-8 with a replacement fallback, so a log line can never take down a run.
"""

import sys


def ensure_utf8_console() -> None:
    """Force stdout/stderr to UTF-8 where the platform allows it.

    Safe to call repeatedly, and a no-op on streams that are already UTF-8 or
    that have been replaced (pytest capture, pipes, redirects to a file).
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            # Not a real text stream (captured or wrapped) — nothing to fix.
            continue
        encoding = (getattr(stream, "encoding", "") or "").lower()
        if encoding.replace("-", "") == "utf8":
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # A stream that refuses reconfiguration is left as-is; callers
            # still have safe_print() below as a backstop.
            pass


def safe_print(*args, **kwargs) -> None:
    """print() that degrades instead of raising on an unencodable character."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        encoding = (getattr(sys.stdout, "encoding", "") or "utf-8")
        cleaned = [
            str(a).encode(encoding, errors="replace").decode(encoding, errors="replace")
            for a in args
        ]
        print(*cleaned, **kwargs)
