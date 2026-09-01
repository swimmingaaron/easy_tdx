"""Strategy Evaluation Agent for 15 Daily Stock Analysis Strategies."""
from __future__ import annotations
from typing import Any
import pandas as pd
from easy_tdx.strategies.registry import get_strategy, list_strategies

DAILY_ANALYSIS_STRATEGY_IDS = [
    "bottom_volume", "box_oscillation", "bull_trend", "chan_theory_daily",
    "dragon_head_momentum", "emotion_cycle_daily", "event_driven",
    "expectation_repricing", "growth_quality", "hot_theme_resonance",
    "ma_golden_cross_daily", "one_yang_three_yin", "shrink_pullback",
    "volume_breakout_platform", "wave_theory_impulse"
]

class StrategyAgent:
    """Evaluates a stock against 15 daily_stock_analysis quant strategies."""
    
    def evaluate_stock_strategies(self, symbol: str, kline_df: pd.DataFrame) -> list[dict[str, Any]]:
        results = []
        if kline_df.empty or len(kline_df) < 20:
            return results

        for st_id in DAILY_ANALYSIS_STRATEGY_IDS:
            st = get_strategy(st_id)
            if not st:
                continue
                
            try:
                sig_df = st.generate_signals(kline_df)
                last_row = sig_df.iloc[-1]
                buy_today = bool(last_row.get("buy_signal", False))
                
                # Check recent 5 days triggers count
                recent_5d = sig_df.iloc[-5:] if len(sig_df) >= 5 else sig_df
                recent_triggers = int(recent_5d["buy_signal"].sum()) if "buy_signal" in recent_5d else 0
                
                # Match score
                match_score = 90.0 if buy_today else (75.0 if recent_triggers > 0 else 45.0)
                
                results.append({
                    "strategy_name": st.name,
                    "display_name": st.display_name,
                    "description": st.description,
                    "is_triggered_today": buy_today,
                    "recent_triggers_5d": recent_triggers,
                    "match_score": match_score,
                    "status_badge": "今日触发买点" if buy_today else ("近5日有信号" if recent_triggers > 0 else "未触发")
                })
            except Exception as e:
                results.append({
                    "strategy_name": st.name,
                    "display_name": st.display_name,
                    "description": st.description,
                    "is_triggered_today": False,
                    "recent_triggers_5d": 0,
                    "match_score": 50.0,
                    "status_badge": "评估中"
                })

        # Sort: triggered today first, then highest score
        results.sort(key=lambda x: (not x["is_triggered_today"], -x["match_score"]))
        return results

strategy_agent = StrategyAgent()
