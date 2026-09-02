"""Trade ledger: append-only records of what reached the broker."""

import json
import tempfile
import unittest
from pathlib import Path

from tradingagents import ledger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.config = {"results_dir": self._dir.name}

    def tearDown(self):
        self._dir.cleanup()

    def _path(self):
        return Path(self._dir.name) / ledger.LEDGER_FILENAME

    def test_entry_records_the_gates_numbers_not_the_models(self):
        ledger.record_entry(
            symbol="TSLA",
            order_id="abc-123",
            strategy="iron_condor",
            legs=[{"symbol": "TSLA260911C00360000", "side": "sell"}],
            limit_price=8.14,
            quantity=1,
            signal="neutral",
            gate={"max_loss_usd": 640.0, "net_credit_debit": -8.0},
            config=self.config,
        )
        records = ledger.read_records(self.config)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "entry")
        self.assertEqual(records[0]["max_loss_usd"], 640.0)
        self.assertEqual(records[0]["net_credit_debit"], -8.0)

    def test_exit_records_the_rule_that_fired(self):
        ledger.record_exit(
            symbol="TSLA",
            order_id="def-456",
            reason="stop loss: down $1,200.00 against a $800.00 credit",
            group_key="TSLA:2026-09-11",
            premium=800.0,
            unrealized_pl=-1200.0,
            structure="credit",
            dte=9,
            config=self.config,
        )
        record = ledger.read_records(self.config)[0]
        self.assertEqual(record["kind"], "exit")
        self.assertEqual(record["unrealized_pl_at_decision"], -1200.0)

    def test_fills_fold_onto_their_order_without_rewriting_history(self):
        ledger.record_entry(symbol="TSLA", order_id="abc-123", config=self.config)
        ledger.record_fill(order_id="abc-123", status="filled", filled_qty=1,
                           filled_avg_price=8.10, config=self.config)

        # History is append-only: both records survive.
        self.assertEqual(len(ledger.read_records(self.config)), 2)

        orders = ledger.load_orders(self.config)
        self.assertEqual(len(orders), 1)  # one order, not one per record
        self.assertEqual(orders[0]["fill_status"], "filled")
        self.assertEqual(orders[0]["filled_avg_price"], 8.10)

    def test_latest_fill_wins(self):
        ledger.record_entry(symbol="X", order_id="o1", config=self.config)
        ledger.record_fill(order_id="o1", status="accepted", config=self.config)
        ledger.record_fill(order_id="o1", status="filled", config=self.config)
        self.assertEqual(ledger.load_orders(self.config)[0]["fill_status"], "filled")

    def test_a_torn_line_does_not_lose_the_rest_of_the_file(self):
        ledger.record_entry(symbol="A", order_id="o1", config=self.config)
        with self._path().open("a", encoding="utf-8") as handle:
            handle.write('{"kind": "entry", "symbol": "B"\n')  # interrupted write
        ledger.record_entry(symbol="C", order_id="o3", config=self.config)

        symbols = [r.get("symbol") for r in ledger.read_records(self.config)]
        self.assertEqual(symbols, ["A", "C"])

    def test_summary_groups_exit_reasons_by_rule(self):
        ledger.record_exit(symbol="A", order_id="e1",
                           reason="stop loss: down $10", config=self.config)
        ledger.record_exit(symbol="B", order_id="e2",
                           reason="stop loss: down $20", config=self.config)
        ledger.record_exit(symbol="C", order_id="e3",
                           reason="time exit: 9 days to expiry", config=self.config)
        summary = ledger.summarize(self.config)
        self.assertEqual(summary["exits"], 3)
        self.assertEqual(summary["exit_reasons"], {"stop loss": 2, "time exit": 1})
        self.assertEqual(summary["symbols"], ["A", "B", "C"])

    def test_missing_ledger_reads_as_empty_not_an_error(self):
        self.assertEqual(ledger.read_records(self.config), [])
        self.assertEqual(ledger.summarize(self.config)["entries"], 0)

    def test_a_write_failure_is_reported_not_raised(self):
        # Visibility must never be able to break a trade: by the time the
        # ledger is written the order is already live at the broker.
        bad = {"results_dir": str(Path(self._dir.name) / "nope") + "\0invalid"}
        self.assertFalse(ledger.record_entry(symbol="X", order_id="o", config=bad))

    def test_reconcile_skips_orders_with_a_terminal_status(self):
        ledger.record_entry(symbol="A", order_id="done", config=self.config)
        ledger.record_fill(order_id="done", status="filled", config=self.config)
        report = ledger.reconcile(self.config)
        self.assertEqual(report["checked"], 0)
        self.assertEqual(report["updated"], 0)

    def test_records_are_valid_jsonl(self):
        ledger.record_entry(symbol="A", order_id="o1", config=self.config)
        ledger.record_exit(symbol="A", order_id="o2", reason="time exit",
                           config=self.config)
        with self._path().open("r", encoding="utf-8") as handle:
            lines = [line for line in handle if line.strip()]
        self.assertEqual(len(lines), 2)
        for line in lines:
            json.loads(line)  # each line stands alone


if __name__ == "__main__":
    unittest.main()
