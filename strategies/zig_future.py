"""ZIG 之字转向未来函数策略。

基于通达信经典的 ZIG 指标，在价格波谷探明后买入，波峰见顶后卖出。

⚠️ 重要提示（未来函数说明）：
ZIG 指标属于典型未来函数（Future Function），其拐点是根据后验价格走势反推确立的。
在历史回测中该策略可实现接近完美的低吸高抛（常作为理论收益天花板对比基准），
但不可直接用于无延迟的实时交易。

用法::

    easy-tdx backtest SZ 000001 --strategy-file strategies/zig_future.py --table
    easy-tdx backtest SH 600519 --strategy-file strategies/zig_future.py --cash 100000 --table
"""

from easy_tdx import MyTT
from easy_tdx.backtest import Strategy


class ZigFutureStrategy(Strategy):
    """ZIG 之字转向未来函数策略。"""

    def init(self) -> None:
        # X=15.0 表示 15% 转向阈值
        self.zig = self.I(MyTT.ZIG, self.data.close, 15.0)

    def next(self) -> None:
        i = self._bar_index
        if i == 0:
            return

        cur_zig = float(self.zig[i])
        prev_zig = float(self.zig[i - 1])

        # 当 ZIG 向上反弹（斜率为正）且当前空仓时全仓买入
        if cur_zig > prev_zig and self.position["size"] == 0:
            self.buy(size=0)
        # 当 ZIG 见顶回落（斜率为负）且当前持仓时全部卖出
        elif cur_zig < prev_zig and self.position["size"] > 0:
            self.sell(size=0)
