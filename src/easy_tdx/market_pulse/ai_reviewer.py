"""Market Pulse AI Reviewer wrapper."""
from easy_tdx.ai.market_reviewer import market_reviewer

class AIReviewer:
    """Wrapper providing market review services."""
    def get_review(self):
        return market_reviewer.generate_daily_review()

ai_reviewer = AIReviewer()
