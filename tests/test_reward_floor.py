"""The gate must reject trades that are safe but not worth taking.

Bounding the loss is not the same as the trade earning anything. A structure
collecting $8 against $250 of risk passes every risk check and still loses
money over repetitions, and a malformed structure -- legs that do not add up to
the strategy they are labelled as -- surfaces here as a reward near zero.
"""

import unittest

from tradingagents.agents.options_risk_gate import _max_reward
from tradingagents.agents.schemas import OptionsLeg, OptionsStrategy, OptionsStrategyProposal


def _proposal(strikes, strategy=OptionsStrategy.IRON_CONDOR):
    return OptionsStrategyProposal(
        strategy=strategy,
        symbol="NVDA",
        direction="neutral",
        legs=[
            OptionsLeg(symbol=f"NVDA26X{int(k*1000):08d}", side=side, ratio_qty=1,
                       strike=k, expiry="2026-09-11", option_type="call")
            for k, side in strikes
        ],
    )


class TestRewardFloor(unittest.TestCase):
    def test_credit_structure_reward_is_the_credit_kept(self):
        p = _proposal([(217.5, "sell"), (220.0, "buy")])
        self.assertEqual(_max_reward(p, -45.0, 205.0), 45.0)

    def test_thin_credit_against_wide_risk_is_below_the_floor(self):
        """The live case: $8 collected against $250 at risk."""
        p = _proposal([(217.5, "sell"), (220.0, "buy")])
        reward = _max_reward(p, -8.0, 250.0)
        self.assertLess(reward / 250.0, 0.25)

    def test_debit_structure_reward_is_width_less_the_debit(self):
        # 217.5/220 is 2.5 wide = $250; paying $100 leaves $150 to make.
        p = _proposal([(217.5, "buy"), (220.0, "sell")])
        self.assertEqual(_max_reward(p, 100.0, 100.0), 150.0)

    def test_healthy_debit_spread_clears_the_floor(self):
        p = _proposal([(217.5, "buy"), (222.5, "sell")])
        reward = _max_reward(p, 200.0, 200.0)
        self.assertGreaterEqual(reward / 200.0, 0.25)

    def test_single_leg_debit_cannot_be_derived(self):
        p = _proposal([(217.5, "buy")], strategy=OptionsStrategy.LONG_CALL)
        self.assertIsNone(_max_reward(p, 480.0, 480.0))


if __name__ == "__main__":
    unittest.main()
