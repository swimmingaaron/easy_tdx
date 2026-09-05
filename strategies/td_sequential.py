"""通达信上升九转策略。

只做上升九转：高1顺势主升突破建仓，高9见顶衰竭逢高止盈，专做单边主升浪大行情。

用法::

    easy-tdx backtest SZ 000001 --strategy-file strategies/td_sequential.py --table
"""

from easy_tdx.backtest import Strategy
from easy_tdx.MyTT import TD_SEQUENTIAL


class TDSequentialStrategy(Strategy):
    """通达信上升九转策略。"""

    m: int = 9
    max_hold_bars: int = 12
    stop_loss_pct: float = 5.0
    take_profit_pct: float = 0.0

    def init(self) -> None:
        self.td_high, _ = self.I(TD_SEQUENTIAL, self.data.close, self.m)
        self.entry_price = 0.0
        self.entry_bar = 0

    def next(self) -> None:
        idx = self._bar_index
        cur_c = float(self.data.close[0])

        if self.position["size"] == 0:
            if self.td_high[idx] == 1:
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
