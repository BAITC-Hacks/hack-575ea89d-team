"""Submission entry point. Run from the repository root."""
from strategy.planner import plan_campaigns


class Agent:
    def act(self, env) -> list[dict]:
        return plan_campaigns(env)
