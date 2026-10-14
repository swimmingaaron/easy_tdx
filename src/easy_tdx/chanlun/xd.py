"""线段计算（特征序列分型法）。

缠论线段定义与划分标准（第65/67/71课）：
1. 线段由至少 3 笔构成，且前三笔必须有价格重叠区间；
2. 特征序列（Characteristic Sequence）：
   - 向上线段的特征序列由该线段中的所有「向下笔」构成；
   - 向下线段的特征序列由该线段中的所有「向上笔」构成；
3. 特征序列包含处理：
   - 向上线段的向下笔特征序列按向下方向进行包含处理；
   - 向下线段的向上笔特征序列按向上方向进行包含处理；
4. 线段破坏判定：
   - 第一种情况（无缺口）：特征序列第一元素与第二元素有重叠。特征序列出现反向分型时，线段在此确认结束；
   - 第二种情况（有缺口）：特征序列第一、二元素存在跳空缺口。特征序列分型后，必须跌破分型极值或形成反向包含确立破坏；
5. 几何连续性：线段首尾相接，方向严格交替。
"""

from __future__ import annotations

from dataclasses import dataclass

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import BI, XD, Direction, FXType


@dataclass
class _CharSeqElement:
    """特征序列元素（将对应方向的笔视为特征序列 K 线）。"""

    bi: BI
    high: float
    low: float
    index: int


def _merge_char_seq(elements: list[_CharSeqElement], direction: Direction) -> list[_CharSeqElement]:
    """对特征序列元素进行包含处理。"""
    if not elements:
        return []

    merged: list[_CharSeqElement] = [elements[0]]

    for i in range(1, len(elements)):
        curr = elements[i]
        prev = merged[-1]

        # 包含判断
        is_inc = (prev.high >= curr.high and prev.low <= curr.low) or \
                 (curr.high >= prev.high and curr.low <= prev.low)

        if is_inc:
            if direction == Direction.UP:
                # 向上线段的向下笔特征序列：取低低（向下合并）
                prev.high = min(prev.high, curr.high)
                prev.low = min(prev.low, curr.low)
            else:
                # 向下线段的向上笔特征序列：取高高（向上合并）
                prev.high = max(prev.high, curr.high)
                prev.low = max(prev.low, curr.low)
        else:
            curr.index = len(merged)
            merged.append(curr)

    return merged


def find_xds(
    bis: list[BI],
    config: ChanlunConfig | None = None,
) -> list[XD]:
    """从笔列表中计算线段（标准特征序列分型划分法）。

    Args:
        bis: 笔列表（需首尾相连）
        config: 缠论配置

    Returns:
        线段列表（首尾相接、方向交替、每段至少3笔）
    """
    if config is None:
        config = ChanlunConfig()

    if len(bis) < 3:
        return []

    xds: list[XD] = []

    # 1. 寻找第一条线段的起始笔与方向
    # 线段方向由前3笔是否有重叠确定
    start_bi_idx = 0

    while start_bi_idx <= len(bis) - 3:
        b0 = bis[start_bi_idx]
        b1 = bis[start_bi_idx + 1]
        b2 = bis[start_bi_idx + 2]

        overlap_high = min(b0.high, b1.high, b2.high)
        overlap_low = max(b0.low, b1.low, b2.low)

        if overlap_high > overlap_low:
            # 找到初始线段方向
            seg_dir = b0.direction
            break
        start_bi_idx += 1

    if start_bi_idx > len(bis) - 3:
        # 笔数不足或全无重叠，若笔较多回退生成一条概括性大线段
        if len(bis) >= 3:
            dir_val = Direction.UP if bis[-1].high > bis[0].low else Direction.DOWN
            h_val = max(b.high for b in bis)
            l_val = min(b.low for b in bis)
            return [XD(start=bis[0].start, end=bis[-1].end, direction=dir_val, index=0, high=h_val, low=l_val)]
        return []

    curr_start_bi_idx = start_bi_idx
    curr_dir = bis[start_bi_idx].direction

    i = curr_start_bi_idx + 3
    while i <= len(bis):
        sub_bis = bis[curr_start_bi_idx:i]
        if len(sub_bis) < 3:
            i += 1
            continue

        # 提取特征序列：向上线段取向下笔，向下线段取向上笔
        target_char_dir = Direction.DOWN if curr_dir == Direction.UP else Direction.UP
        char_bis = [b for b in sub_bis if b.direction == target_char_dir]

        if len(char_bis) >= 3:
            # 转换为特征元素并进行包含处理
            char_elems = [_CharSeqElement(bi=b, high=b.high, low=b.low, index=idx) for idx, b in enumerate(char_bis)]
            merged_chars = _merge_char_seq(char_elems, curr_dir)

            # 寻找特征序列的分型
            has_break = False
            break_bi = None

            if len(merged_chars) >= 3:
                for k in range(len(merged_chars) - 2):
                    c0 = merged_chars[k]
                    c1 = merged_chars[k + 1]
                    c2 = merged_chars[k + 2]

                    if curr_dir == Direction.UP:
                        # 向上线段寻找特征序列顶分型 (c1 最高)
                        if c1.high > c0.high and c1.high > c2.high:
                            has_break = True
                            # 终点取特征序列顶分型前一个向上笔的高点
                            # 找到 c1 对应笔之前的那个同向向上笔
                            c1_orig_idx = c1.bi.index
                            # 寻找对应极值笔
                            cands = [b for b in sub_bis if b.direction == Direction.UP and b.index <= c1_orig_idx]
                            break_bi = max(cands, key=lambda b: b.high) if cands else sub_bis[-1]
                            break
                    else:
                        # 向下线段寻找特征序列底分型 (c1 最低)
                        if c1.low < c0.low and c1.low < c2.low:
                            has_break = True
                            c1_orig_idx = c1.bi.index
                            cands = [b for b in sub_bis if b.direction == Direction.DOWN and b.index <= c1_orig_idx]
                            break_bi = min(cands, key=lambda b: b.low) if cands else sub_bis[-1]
                            break

            if has_break and break_bi is not None:
                # 确认线段成立
                end_bi_idx = break_bi.index
                # 该线段包含的笔
                seg_bis = [b for b in bis if curr_start_bi_idx <= b.index <= end_bi_idx]
                if len(seg_bis) >= 3:
                    h_val = max(b.high for b in seg_bis)
                    l_val = min(b.low for b in seg_bis)
                    xd = XD(
                        start=seg_bis[0].start,
                        end=seg_bis[-1].end,
                        direction=curr_dir,
                        index=len(xds),
                        high=h_val,
                        low=l_val,
                    )
                    xds.append(xd)
                    # 下一线段从断点笔开始
                    curr_start_bi_idx = end_bi_idx
                    curr_dir = Direction.DOWN if curr_dir == Direction.UP else Direction.UP
                    i = curr_start_bi_idx + 3
                    continue

        i += 1

    # 处理最后一段未完成的延伸线段（进行中）
    if curr_start_bi_idx < len(bis):
        tail_bis = bis[curr_start_bi_idx:]
        if len(tail_bis) >= 3:
            h_val = max(b.high for b in tail_bis)
            l_val = min(b.low for b in tail_bis)
            xd = XD(
                start=tail_bis[0].start,
                end=tail_bis[-1].end,
                direction=curr_dir,
                index=len(xds),
                high=h_val,
                low=l_val,
            )
            xds.append(xd)

    return xds
