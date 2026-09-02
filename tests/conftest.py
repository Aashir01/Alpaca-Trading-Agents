"""Test-wide safety net.

Two protections live here, both learned the hard way.

tradingagents.default_config calls load_dotenv() at import time, so a developer
.env leaks into the test environment. With ALPACA_USE_MCP=true that turned the
mocked-broker tests in test_options_executor.py into calls against Alpaca's
real MCP server -- a test run could place live paper orders. Tests must never
reach a broker, so the flag is forced off for the whole suite; the MCP path has
its own dedicated tests that patch the transport.
"""

import os
import tempfile

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


@pytest.fixture(autouse=True, scope="session")
def _isolate_recorded_data():
    """Point every on-disk store at a throwaway directory.

    The run logger and the trade ledger both write under results_dir, which
    defaults to the real eval_results/. A test that exercises the submission
    path therefore appended fake order ids to the operator's actual trade
    history -- and on a deployed box, running the suite would corrupt the
    record of real trades. Redirecting the whole suite is safer than asking
    every future test to remember.
    """
    previous = os.environ.get("TRADINGAGENTS_RESULTS_DIR")
    with tempfile.TemporaryDirectory(prefix="tradingagents-tests-") as scratch:
        os.environ["TRADINGAGENTS_RESULTS_DIR"] = scratch
        yield
    if previous is None:
        os.environ.pop("TRADINGAGENTS_RESULTS_DIR", None)
    else:
        os.environ["TRADINGAGENTS_RESULTS_DIR"] = previous
