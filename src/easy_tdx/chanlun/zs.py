"""中枢计算（标准缠中说禅走势中枢）。

缠论走势中枢定义（第17课、第35课）：
1. 某级别走势类型中，被至少三个连续次级别走势类型（如笔或线段）所重叠的部分，称为缠中说禅走势中枢。
2. 前三笔确定中枢的核心区间：
   - ZG（中枢上沿）= min(bi[0].high, bi[1].high, bi[2].high)
   - ZD（中枢下沿）= max(bi[0].low, bi[1].low, bi[2].low)
   - 中枢有效成立条件：ZG > ZD。
3. 中枢延伸原则（中枢震荡）：
   - 中枢区间 [ZD, ZG] 一旦由前三笔确定，在后续震荡中保持恒定，绝不因延伸笔缩小！
   - 后续笔若与 [ZD, ZG] 有价格交集（bi.high >= ZD 且 bi.low <= ZG），则归属于该中枢的震荡延伸；
   - 震荡过程中动态更新中枢极大极小值：
     GG = max(GG, bi.high)
     DD = min(DD, bi.low)
4. 中枢完成与离开：
   - 当出现不与 [ZD, ZG] 重叠的笔时（向上突破 bi.low > ZG 或 向下跌破 bi.high < ZD），中枢宣告完成 (done=True)；
   - 最后一笔未离开时标记为进行中 (done=False)。
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import BI, XD, ZS, Direction


def find_zss(
    bis: list[BI | XD],
    config: ChanlunConfig | None = None,
) -> list[ZS]:
    """从笔（或线段）列表中计算标准缠论走势中枢。

    Args:
        bis: 笔或线段列表
        config: 缠论配置

    Returns:
        中枢列表
    """
    if config is None:
        config = ChanlunConfig()

    if len(bis) < 3:
        return []

    min_lines = getattr(config, "zs_min_lines", 3)
    zss: list[ZS] = []
    n = len(bis)
    i = 0

    while i <= n - 3:
        b0 = bis[i]
        b1 = bis[i + 1]
        b2 = bis[i + 2]

        # 计算前三笔的重叠区间
        zg = min(b0.high, b1.high, b2.high)
        zd = max(b0.low, b1.low, b2.low)

        if zg > zd:
            # 前三笔重叠成立，创建标准中枢
            gg = max(b0.high, b1.high, b2.high)
            dd = min(b0.low, b1.low, b2.low)
            dir_str = "up" if b0.direction == Direction.DOWN else "down"

            zs = ZS(
                lines=[b0, b1, b2],
                zg=zg,
                zd=zd,
                gg=gg,
                dd=dd,
                direction=dir_str,
                index=len(zss),
                done=False,
                start=b0.start,
                end=b2.end,
            )

            # 检查后续笔是否属于中枢的震荡延伸
            curr_idx = i + 3
            while curr_idx < n:
                next_bi = bis[curr_idx]
                # 判断是否与基准区间 [ZD, ZG] 重叠
                if next_bi.high >= zs.zd and next_bi.low <= zs.zg:
                    # 属于中枢延伸震荡
                    zs.add_line(next_bi)
                    zs.gg = max(zs.gg, next_bi.high)
                    zs.dd = min(zs.dd, next_bi.low)
                    zs.end = next_bi.end
                    curr_idx += 1
                else:
                    # 不再重叠：离开中枢
                    break

            # 如果中枢满足最小笔数要求，加入列表
            if zs.line_count >= min_lines:
                # 若还有后续笔，说明中枢已被打破完成；否则进行中
                zs.done = (curr_idx < n)
                zss.append(zs)
                # 下一个中枢候选从离开笔（或突破笔）之后开始探索，杜绝将离开段重叠进新中枢
                i = max(i + 1, curr_idx)
            else:
                i += 1
        else:
            # 前三笔无重叠，指针后移
            i += 1

    return zss
