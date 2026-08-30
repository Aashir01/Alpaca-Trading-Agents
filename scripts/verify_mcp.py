#!/usr/bin/env python
"""Prove that broker access runs through Alpaca's official MCP server.

The hackathon requires the project to use Alpaca's Trading API *and* either its
MCP server or CLI. This script demonstrates the MCP path end to end without
placing an order: it starts the server, lists the tools it exposes, and reads
the account, positions, and orders back through it.

    python scripts/verify_mcp.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from tradingagents.mcp_client import (  # noqa: E402
    AlpacaMCPError,
    alpaca_mcp_enabled,
    call_alpaca_tool,
    get_alpaca_mcp,
)


def _unwrap(payload):
    if isinstance(payload, dict) and "result" in payload:
        return payload["result"]
    return payload


def main() -> int:
    print(f"ALPACA_USE_MCP = {alpaca_mcp_enabled()}")
    if not alpaca_mcp_enabled():
        print("Set ALPACA_USE_MCP=true in .env to route broker calls through MCP.")
        return 1

    try:
        account = call_alpaca_tool("get_account_info")
    except AlpacaMCPError as exc:
        print(f"FAILED: {exc}")
        return 1

    tools = get_alpaca_mcp().tools
    print(f"\nMCP server connected — {len(tools)} tools exposed")
    for name in ("get_account_info", "get_option_chain", "place_option_order",
                 "get_all_positions", "get_orders"):
        print(f"  {'OK  ' if name in tools else 'MISS'} {name}")

    print("\nAccount (read through MCP)")
    print(f"  number : {account.get('account_number')}")
    print(f"  status : {account.get('status')}")
    print(f"  equity : {account.get('equity')}")
    print(f"  options level : {account.get('options_trading_level')}")

    positions = _unwrap(call_alpaca_tool("get_all_positions")) or []
    print(f"\nPositions (read through MCP): {len(positions)}")
    for p in positions[:5]:
        print(f"  {p.get('symbol')}: qty={p.get('qty')} value={p.get('market_value')} pl={p.get('unrealized_pl')}")

    orders = _unwrap(call_alpaca_tool("get_orders", {"limit": "5", "status": "all"})) or []
    print(f"\nRecent orders (read through MCP): {len(orders)}")
    for o in orders[:5]:
        label = o.get("symbol") or "(multi-leg)"
        print(f"  {label}: class={o.get('order_class') or 'simple'} qty={o.get('qty')} status={o.get('status')}")
        for leg in (o.get("legs") or []):
            print(f"      leg {leg.get('symbol')} {leg.get('side')} x{leg.get('ratio_qty')}")

    print("\nBroker access verified through Alpaca's official MCP server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
