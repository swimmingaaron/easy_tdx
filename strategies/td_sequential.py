"""通达信九转交易策略。

支持高1顺势主升买入与低9超跌反转买入，并在高9见顶时逢高止盈，结合最长持有期与硬止损保护。

用法::

    easy-tdx backtest SZ 000001 --strategy-file strategies/td_sequential.py --table
"""

from easy_tdx.backtest import Strategy
from easy_tdx.MyTT import TD_SEQUENTIAL


class TDSequentialStrategy(Strategy):
    """通达信九转策略。"""

    m: int = 9
    trade_mode: str = "both"  # "both", "trend", "reversal"
    max_hold_bars: int = 15
    stop_loss_pct: float = 5.0
    take_profit_pct: float = 0.0

    def init(self) -> None:
        self.td_high, self.td_low = self.I(TD_SEQUENTIAL, self.data.close, self.m)
        self.entry_price = 0.0
        self.entry_bar = 0

    def next(self) -> None:
        idx = self._bar_index
        cur_c = float(self.data.close[0])

        if self.position["size"] == 0:
            can_buy = False
            if self.trade_mode in ("both", "reversal") and self.td_low[idx] == self.m:
                can_buy = True
            elif self.trade_mode in ("both", "trend") and self.td_high[idx] == 1:
                can_buy = True

            if can_buy:
                self.buy(size=0)
                self.entry_price = cur_c
                self.entry_bar = idx
        else:
            is_high_m = (self.td_high[idx] == self.m)
            is_sl = (self.stop_loss_pct > 0) and (cur_c < self.entry_price * (1.0 - self.stop_loss_pct / 100.0))
            is_tp = (self.take_profit_pct > 0) and (cur_c >= self.entry_price * (1.0 + self.take_profit_pct / 100.0))
            is_timeout = (self.max_hold_bars > 0) and (idx - self.entry_bar >= self.max_hold_bars)

            if is_high_m or is_sl or is_tp or is_timeout:
                self.sell(size=0)
                self.entry_price = 0.0
