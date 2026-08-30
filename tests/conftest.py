"""Test-wide safety net.

tradingagents.default_config calls load_dotenv() at import time, so a developer
.env leaks into the test environment. With ALPACA_USE_MCP=true that turned the
mocked-broker tests in test_options_executor.py into calls against Alpaca's
real MCP server -- a test run could place live paper orders. Tests must never
reach a broker, so the flag is forced off for the whole suite; the MCP path has
its own dedicated tests that patch the transport.
"""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _disable_broker_transports():
    previous = os.environ.get("ALPACA_USE_MCP")
    os.environ["ALPACA_USE_MCP"] = "false"
    yield
    if previous is None:
        os.environ.pop("ALPACA_USE_MCP", None)
    else:
        os.environ["ALPACA_USE_MCP"] = previous
