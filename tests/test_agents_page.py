"""The Agents page must stay in step with the graph it describes.

Its value is that the roster and prompts are real: every agent named here is an
agent the run reports status for, and every prompt listed is a template that
exists. A rename on either side should fail loudly here rather than silently
producing a page that describes a pipeline the app no longer has.
"""

import unittest

from tradingagents.prompts import PromptTemplateError, load_prompt
from webui.components.agents import AGENT_PROMPTS, ALL_AGENTS, create_agents_page
from webui.utils.state import AppState


class TestAgentsPage(unittest.TestCase):
    def test_every_listed_prompt_template_exists(self):
        for agent, prompts in AGENT_PROMPTS.items():
            for name in prompts:
                try:
                    self.assertTrue(load_prompt(name).strip(), f"{agent}: {name} is empty")
                except PromptTemplateError as exc:
                    self.fail(f"{agent} references a missing template {name}: {exc}")

    def test_roster_matches_the_agents_the_graph_reports(self):
        state = AppState()
        state.init_symbol_state("NVDA")
        tracked = set(state.symbol_states["NVDA"]["agent_statuses"])
        listed = {name for name, _icon, _role, _prompts in ALL_AGENTS}
        self.assertEqual(listed, tracked)

    def test_every_agent_has_a_role_and_at_least_one_prompt(self):
        for name, icon, role, prompts in ALL_AGENTS:
            self.assertTrue(icon.startswith("fa-"), f"{name} has no icon")
            self.assertTrue(role.strip(), f"{name} has no role description")
            self.assertTrue(prompts, f"{name} has no prompts")

    def test_page_builds(self):
        self.assertTrue(create_agents_page())


if __name__ == "__main__":
    unittest.main()
