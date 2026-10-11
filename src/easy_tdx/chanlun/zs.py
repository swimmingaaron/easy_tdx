"""中枢计算。

中枢定义：至少三笔（或线段）的价格区间有重叠。
- zg（上沿）= 重叠区间的最高点
- zd（下沿）= 重叠区间的最低点
- gg = 中枢内所有笔的最高价
- dd = 中枢内所有笔的最低价

标准中枢算法：
1. 逐笔扫描，维护当前中枢的 zg/zd
2. 新笔进入时，更新 gg/dd
3. 新笔离开（不再与 [zd, zg] 重叠）时，关闭中枢

优化（v2）：
1. 修复 `if len(zss) == 0 or True:` 逻辑错误（永远 True 是冗余代码）
2. 新笔无法延续中枢时，尝试从最后两笔形成新中枢候选（而非单笔重置）
3. 中枢 done 状态修正：被新笔打破时标记 done=True，末尾中枢 done=False
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import BI, ZS


def _init_zs_from_bi(bi: BI, index: int) -> ZS:
    """用单笔初始化一个候选中枢。"""
    return ZS(
        lines=[bi],
        zg=bi.high,
        zd=bi.low,
        gg=bi.high,
        dd=bi.low,
        start=bi.start,
        end=bi.end,
        index=index,
    )


def find_zss(
    bis: list[BI],
    config: ChanlunConfig | None = None,
) -> list[ZS]:
    """从笔列表中计算中枢。

    算法：
    1. 逐笔扫描
    2. 维护当前中枢的 zg/zd（重叠区间）
    3. 新笔与 [zd, zg] 有重叠 → 加入中枢，更新重叠区间
    4. 新笔与 [zd, zg] 无重叠 → 关闭当前中枢（若达到最小笔数），开始新候选

    Args:
        bis: 笔列表
        config: 缠论配置

    Returns:
        中枢列表
    """
    if config is None:
        config = ChanlunConfig()

    if len(bis) < 3:
        return []

    zss: list[ZS] = []
    current_zs: ZS | None = None

    for bi in bis:
        if current_zs is None:
            # 用当前笔初始化候选中枢
            current_zs = _init_zs_from_bi(bi, index=len(zss))
            continue

        # 当前笔与中枢是否有重叠
        overlap_high = min(current_zs.zg, bi.high)
        overlap_low = max(current_zs.zd, bi.low)

        if overlap_high > overlap_low:
            # 有重叠，加入中枢，更新重叠区间（缩小）
            current_zs.add_line(bi)
            current_zs.zg = overlap_high
            current_zs.zd = overlap_low
            current_zs.gg = max(current_zs.gg, bi.high)
            current_zs.dd = min(current_zs.dd, bi.low)
            current_zs.end = bi.end
        else:
            # 无重叠：当前笔离开中枢
            if current_zs.line_count >= config.zs_min_lines:
                # 中枢成立，完成并保存
                current_zs.done = True
                zss.append(current_zs)
                # 以最后两笔（倒数第一笔在中枢内、当前笔在中枢外）作为新候选起点
                # 从中枢最后一笔开始新中枢（保持连续性）
                last_in_zs = current_zs.lines[-1]
                current_zs = _init_zs_from_bi(last_in_zs, index=len(zss))
                # 立即尝试把当前笔加入新候选
                overlap_high2 = min(current_zs.zg, bi.high)
                overlap_low2 = max(current_zs.zd, bi.low)
                if overlap_high2 > overlap_low2:
                    current_zs.add_line(bi)
                    current_zs.zg = overlap_high2
                    current_zs.zd = overlap_low2
                    current_zs.gg = max(current_zs.gg, bi.high)
                    current_zs.dd = min(current_zs.dd, bi.low)
                    current_zs.end = bi.end
                else:
                    # 新候选也无法延续，重新以当前笔初始化
                    current_zs = _init_zs_from_bi(bi, index=len(zss))
            else:
                # 中枢笔数不足，丢弃，用当前笔重新开始
                current_zs = _init_zs_from_bi(bi, index=len(zss))

    # 处理最后一个候选中枢
    if current_zs is not None and current_zs.line_count >= config.zs_min_lines:
        current_zs.done = False  # 最后一根K线未确定，中枢进行中
        zss.append(current_zs)

    return zss
