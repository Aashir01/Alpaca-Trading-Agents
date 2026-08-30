"""A synchronous facade over Alpaca's official MCP server.

The server (``uvx alpaca-mcp-server``) speaks MCP over stdio and the SDK for it
is asyncio-only, while this codebase is synchronous throughout. Rather than
sprinkle ``asyncio.run`` through the execution path -- which would spawn and
tear down a server process per call, costing seconds on every order -- this
module owns one background event loop, keeps a single session open on it, and
hands callers a plain blocking ``call_alpaca_tool``.

Enable with ``ALPACA_USE_MCP=true``. Every caller falls back to the alpaca-py
SDK when the server is unavailable, so a broken MCP install degrades to the
previous behaviour instead of halting trading.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import threading
from typing import Any, Optional

_TRUTHY = {"1", "true", "yes", "on"}


class AlpacaMCPError(RuntimeError):
    """Raised when the MCP server cannot be reached or a tool call fails."""


def alpaca_mcp_enabled() -> bool:
    return (os.getenv("ALPACA_USE_MCP") or "").strip().lower() in _TRUTHY


def _server_command() -> tuple[str, list[str]]:
    """Command that starts the server, overridable for a pinned install."""
    raw = os.getenv("ALPACA_MCP_COMMAND")
    if raw:
        parts = raw.split()
        return parts[0], parts[1:]
    return "uvx", ["alpaca-mcp-server"]


class AlpacaMCP:
    """Owns a background loop and one long-lived MCP session."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session = None
        self._stack = None
        self._lock = threading.Lock()
        self._tools: list[str] = []

    # -- lifecycle ---------------------------------------------------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=loop.run_forever, name="alpaca-mcp-loop", daemon=True
        )
        thread.start()
        self._loop, self._thread = loop, thread
        atexit.register(self.close)
        return loop

    async def _aconnect(self) -> None:
        from contextlib import AsyncExitStack

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = dict(os.environ)
        env.setdefault("ALPACA_PAPER_TRADE", "true" if _paper() else "false")
        command, args = _server_command()
        params = StdioServerParameters(command=command, args=args, env=env)

        stack = AsyncExitStack()
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listing = await session.list_tools()
        self._tools = [t.name for t in listing.tools]
        self._session, self._stack = session, stack

    def connect(self, timeout: float = 120.0) -> None:
        """Start the server and open a session. Safe to call repeatedly."""
        with self._lock:
            if self._session is not None:
                return
            loop = self._ensure_loop()
            future = asyncio.run_coroutine_threadsafe(self._aconnect(), loop)
            try:
                future.result(timeout=timeout)
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller
                raise AlpacaMCPError(f"Could not start Alpaca MCP server: {exc}") from exc

    def close(self) -> None:
        loop, stack = self._loop, self._stack
        self._session = None
        self._stack = None
        if loop is not None and stack is not None:
            try:
                asyncio.run_coroutine_threadsafe(stack.aclose(), loop).result(timeout=15)
            except Exception:
                pass
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        self._loop = None
        self._thread = None

    # -- calls -------------------------------------------------------------
    @property
    def tools(self) -> list[str]:
        return list(self._tools)

    async def _acall(self, name: str, arguments: dict) -> Any:
        result = await self._session.call_tool(name, arguments)
        text = "".join(
            chunk.text for chunk in result.content if hasattr(chunk, "text")
        )
        if getattr(result, "isError", False):
            raise AlpacaMCPError(f"{name} failed: {text[:400]}")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        # The server wraps replies as {"_alpaca_mcp_security": {...}, "data": ...}
        # and marks them untrusted_tool_output: broker data is data, never
        # instructions. Unwrap the payload and drop the envelope.
        if isinstance(payload, dict) and "data" in payload and "_alpaca_mcp_security" in payload:
            return payload["data"]
        return payload

    def call(self, name: str, arguments: Optional[dict] = None, timeout: float = 120.0) -> Any:
        self.connect()
        loop = self._loop
        if loop is None or self._session is None:
            raise AlpacaMCPError("Alpaca MCP session is not available")
        future = asyncio.run_coroutine_threadsafe(
            self._acall(name, arguments or {}), loop
        )
        try:
            return future.result(timeout=timeout)
        except AlpacaMCPError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AlpacaMCPError(f"MCP tool '{name}' failed: {exc}") from exc


def _paper() -> bool:
    return (os.getenv("ALPACA_USE_PAPER") or "true").strip().lower() in _TRUTHY


_CLIENT: Optional[AlpacaMCP] = None
_CLIENT_LOCK = threading.Lock()


def get_alpaca_mcp() -> AlpacaMCP:
    """Process-wide client. One server process, reused across calls."""
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = AlpacaMCP()
        return _CLIENT


def call_alpaca_tool(name: str, arguments: Optional[dict] = None, timeout: float = 120.0) -> Any:
    return get_alpaca_mcp().call(name, arguments, timeout=timeout)
