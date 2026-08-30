"""Reachability tests for the options overlay.

The options modules were once well-tested in isolation while being imported by
nothing: unit tests passed because they exercised the modules directly. These
tests assert the opposite property - that the node is actually present in the
compiled graph, that the state schema carries the keys it returns, and that the
feature flag genuinely switches it on and off.
"""

import unittest
from unittest.mock import MagicMock

from langgraph.graph import StateGraph

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup


def _build(options_enabled: bool) -> StateGraph:
    config = dict(DEFAULT_CONFIG)
    config["options_trading_enabled"] = options_enabled
    setup = GraphSetup(
        quick_thinking_llm=MagicMock(),
        deep_thinking_llm=MagicMock(),
        toolkit=MagicMock(),
        tool_nodes={
            name: MagicMock()
            for name in ("market", "social", "news", "fundamentals", "macro")
        },
        bull_memory=MagicMock(),
        bear_memory=MagicMock(),
        trader_memory=MagicMock(),
        invest_judge_memory=MagicMock(),
        risk_manager_memory=MagicMock(),
        conditional_logic=ConditionalLogic(),
        config=config,
    )
    return setup.setup_graph(["market"])


class OptionsGraphWiringTests(unittest.TestCase):
    def test_state_schema_carries_options_keys(self):
        """The node returns these keys; LangGraph drops any not in the schema."""
        annotations = AgentState.__annotations__
        self.assertIn("options_strategy_report", annotations)
        self.assertIn("options_trade_plan", annotations)

    def test_node_present_and_reachable_when_enabled(self):
        workflow = _build(options_enabled=True)
        self.assertIn("Options Strategist", workflow.nodes)

        edges = {(src, dst) for src, dst in workflow.edges}
        self.assertIn(("Trader", "Options Strategist"), edges)
        # It must lead into the risk debate, not dead-end.
        outgoing = {dst for src, dst in edges if src == "Options Strategist"}
        self.assertTrue(
            outgoing & {"Parallel Risk Round 1", "Risky Analyst"},
            f"Options Strategist does not reach the risk debate: {outgoing}",
        )
        # The Trader must not also bypass it straight into the risk debate.
        self.assertNotIn(("Trader", "Parallel Risk Round 1"), edges)
        self.assertNotIn(("Trader", "Risky Analyst"), edges)

    def test_node_absent_when_disabled(self):
        workflow = _build(options_enabled=False)
        self.assertNotIn("Options Strategist", workflow.nodes)
        edges = {(src, dst) for src, dst in workflow.edges}
        self.assertTrue(
            {("Trader", "Parallel Risk Round 1"), ("Trader", "Risky Analyst")} & edges,
            "Trader must still reach the risk debate when options are disabled",
        )

    def test_graph_compiles_with_options_enabled(self):
        self.assertIsNotNone(_build(options_enabled=True).compile())


class OptionsStatePropagationTests(unittest.TestCase):
    """LangGraph silently drops returned keys that are not in the state schema.

    That is the failure this guards: the node can return a perfectly good plan
    and the rest of the pipeline still sees nothing.
    """

    def test_node_output_survives_a_langgraph_state_update(self):
        from langgraph.graph import END, START

        plan = {"strategy": "long_call", "symbol": "AAPL"}

        def fake_options_node(_state):
            return {
                "options_strategy_report": "**Options Strategy**: long_call",
                "options_trade_plan": plan,
                "sender": "Options Strategist",
            }

        graph = StateGraph(AgentState)
        graph.add_node("Options Strategist", fake_options_node)
        graph.add_edge(START, "Options Strategist")
        graph.add_edge("Options Strategist", END)

        final = graph.compile().invoke(
            {
                "company_of_interest": "AAPL",
                "trade_date": "2025-01-10",
                "recommended_action": "BUY",
                "messages": [],
            }
        )

        self.assertEqual(final.get("options_trade_plan"), plan)
        self.assertIn("long_call", final.get("options_strategy_report", ""))

    def test_initial_state_seeds_options_keys(self):
        from tradingagents.graph.propagation import Propagator

        state = Propagator().create_initial_state("AAPL", "2025-01-10")
        self.assertIn("options_strategy_report", state)
        self.assertIn("options_trade_plan", state)


class AccountSnapshotTests(unittest.TestCase):
    """The options gate sizes every position off account equity."""

    def test_get_account_info_exposes_equity(self):
        """Regression: equity was absent, so the gate always saw 0.

        With equity 0 the max-allowed-loss allowance is 0, and every options
        trade is vetoed - the agent looks like it is running and never trades.
        """
        from unittest.mock import MagicMock, patch

        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        account = MagicMock()
        account.buying_power = "50000"
        account.cash = "25000"
        account.equity = "100000"
        account.last_equity = "99000"
        account.portfolio_value = "100000"
        client = MagicMock()
        client.get_account.return_value = account

        with patch(
            "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
            return_value=client,
        ):
            info = AlpacaUtils.get_account_info()

        self.assertEqual(info["equity"], 100000.0)
        self.assertEqual(info["daily_change_dollars"], 1000.0)

    def test_gate_allowance_is_nonzero_for_a_funded_account(self):
        """End-to-end: a funded account must produce a real loss allowance."""
        from unittest.mock import MagicMock, patch

        from tradingagents.agents import options_strategist

        with patch.object(options_strategist, "AlpacaUtils") as alpaca:
            alpaca.get_account_info.return_value = {
                "equity": 100000.0, "buying_power": 100000.0, "cash": 50000.0,
            }
            alpaca.get_positions_data.return_value = []
            snapshot = options_strategist._build_account_snapshot()

        self.assertEqual(snapshot["equity"], 100000.0)
        self.assertGreater(snapshot["equity"] * 0.02, 0)


class OptionsConfigTests(unittest.TestCase):
    def test_options_config_keys_exist(self):
        for key in (
            "options_trading_enabled",
            "options_dte_min",
            "options_dte_max",
            "options_max_loss_pct",
            "options_max_spread_pct",
            "options_stress_move_pct",
            "options_max_contracts",
        ):
            self.assertIn(key, DEFAULT_CONFIG)

    def test_risk_limits_actually_reach_the_gate(self):
        """A config key that reaches nothing is worse than no key at all.

        These were declared and documented while the gate still used its own
        defaults, so tightening a limit in .env changed nothing.
        """
        from unittest.mock import patch

        from tradingagents.agents import options_strategist
        from tradingagents.dataflows.options_data import OptionsMarketContext, OptionQuote

        config = {
            "options_trading_enabled": True,
            "options_max_loss_pct": 7.5,
            "options_max_spread_pct": 3.25,
            "options_stress_move_pct": 42.0,
            "options_max_contracts": 4,
        }
        quote = OptionQuote(
            symbol="AAPL250117C00150000", underlying="AAPL", expiry=None, strike=150.0,
            option_type="call", bid=2.5, ask=2.6, last=None, volume=None,
            open_interest=None, iv=0.35, delta=None, gamma=None, theta=None,
            vega=None, underlying_price=150.0,
        )
        context = OptionsMarketContext(
            symbol="AAPL", spot=150.0, atm_iv=0.35, iv_rank=45.0, iv_percentile=0.45,
            hv_20=20.0, days_to_earnings=None, timestamp="2025-01-10T10:00:00",
            iv_history_days=30,
        )

        with patch.object(options_strategist, "AlpacaUtils") as alpaca, \
             patch.object(options_strategist, "fetch_spot_price", return_value=150.0), \
             patch.object(options_strategist, "get_option_chain_context", return_value=[quote]), \
             patch.object(options_strategist, "get_options_market_context",
                          return_value=(context, [quote])), \
             patch.object(options_strategist, "bind_structured") as bind, \
             patch.object(options_strategist, "evaluate_strategy") as gate:
            alpaca.get_account_info.return_value = {"equity": 100000.0, "buying_power": 100000.0}
            alpaca.get_positions_data.return_value = []
            bind.return_value = MagicMock(invoke=MagicMock(return_value=MagicMock()))
            gate.return_value = MagicMock(approved=False, reasons=["stub"])

            node = options_strategist.create_options_strategist(MagicMock(), config)
            node({
                "company_of_interest": "AAPL",
                "recommended_action": "BUY",
                "trader_investment_plan": {"confidence": "high"},
                "trade_date": "2025-01-10",
            })

        kwargs = gate.call_args.kwargs
        self.assertEqual(kwargs["max_loss_pct"], 7.5)
        self.assertEqual(kwargs["max_spread_pct"], 3.25)
        self.assertEqual(kwargs["stress_move_pct"], 42.0)
        self.assertEqual(kwargs["qty"], 4)

    def test_options_env_vars_documented(self):
        from pathlib import Path

        sample = Path("env.sample").read_text(encoding="utf-8")
        for var in (
            "OPTIONS_TRADING_ENABLED",
            "OPTIONS_DTE_MIN",
            "OPTIONS_DTE_MAX",
            "OPTIONS_MAX_LOSS_PCT",
            "OPTIONS_MAX_SPREAD_PCT",
        ):
            self.assertIn(f"{var}=", sample)


if __name__ == "__main__":
    unittest.main()
