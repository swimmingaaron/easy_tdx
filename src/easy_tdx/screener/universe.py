"""Stock Universe definitions for easy_tdx Strategy Screener.

Supports multi-tier scanning scopes:
- core: 核心流动性龙头池 (35 只 · ~1秒极速)
- hs300: 沪深 300 核心权重池 (300 只 · ~6-8秒)
- zz500: 中证 500 成长主力池 (500 只 · ~12-15秒)
- zz1000: 中证 1000 活跃小盘池 (1000 只 · ~25-30秒)
- all: 全市场全 A 股 (5,207 只 · 异步后台全量批处理任务)
"""
from __future__ import annotations
import os
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 1. 核心龙头代表性标的池 (根据东方财富全行业最全龙头名单整理，涵盖全球第一、国内第一、科技细分龙头与40个行业冠军共 159 只)
CORE_UNIVERSE = [
    # 全球第一 / 国际领跑龙头
    "002475",  # 立讯精密
    "002415",  # 海康威视
    "000725",  # 京东方A
    "603160",  # 汇顶科技
    "600745",  # 闻泰科技
    "002241",  # 歌尔股份
    "300628",  # 亿联网络
    "300207",  # 欣旺达
    "600309",  # 万华化学
    "300015",  # 爱尔眼科
    "000661",  # 长春高新
    "601888",  # 中国中免
    "601766",  # 中国中车
    "002050",  # 三花智控
    "688063",  # 派能科技
    "688008",  # 澜起科技
    "600563",  # 法拉电子
    "688256",  # 寒武纪
    "600900",  # 长江电力
    "603993",  # 洛阳钼业
    "601138",  # 工业富联
    "300450",  # 先导智能
    "000338",  # 潍柴动力
    "601088",  # 中国神华
    "002714",  # 牧原股份
    "600660",  # 福耀玻璃
    "300274",  # 阳光电源
    "600438",  # 通威股份
    "002812",  # 恩捷股份
    "002709",  # 天赐材料
    "600436",  # 片仔癀
    "600519",  # 贵州茅台
    "603288",  # 海天味业
    "600885",  # 宏发股份
    "688363",  # 华熙生物
    "002001",  # 新和成
    "603260",  # 合盛硅业
    "600941",  # 中国移动
    "601728",  # 中国电信

    # 国内第一 / 行业领军
    "000063",  # 中兴通讯
    "600703",  # 三安光电
    "600588",  # 用友网络
    "002230",  # 科大讯飞
    "601360",  # 三六零
    "300454",  # 深信服
    "603019",  # 中科曙光
    "002410",  # 广联达
    "002008",  # 大族激光
    "002371",  # 北方华创
    "002841",  # 视源股份
    "300014",  # 亿纬锂能
    "002439",  # 启明星辰
    "002916",  # 深南电路
    "600845",  # 宝信软件
    "603659",  # 璞泰来
    "002152",  # 广电运通
    "300017",  # 网宿科技
    "000997",  # 新大陆
    "002396",  # 星网锐捷
    "002153",  # 石基信息
    "300271",  # 华宇软件
    "002405",  # 四维图新
    "002583",  # 海能达
    "000050",  # 深天马A
    "002281",  # 光迅科技
    "002463",  # 沪电股份

    # 细分科技与半导体芯片龙头
    "300782",  # 卓胜微
    "300750",  # 宁德时代
    "000977",  # 浪潮信息
    "603501",  # 韦尔股份
    "002938",  # 鹏鼎控股
    "002600",  # 领益智造
    "688111",  # 金山办公
    "300433",  # 蓝思科技
    "603986",  # 兆易创新
    "600183",  # 生益科技
    "300383",  # 光环新网
    "600536",  # 中国软件
    "601231",  # 环旭电子
    "600584",  # 长电科技
    "300308",  # 中际旭创
    "603290",  # 斯达半导
    "300661",  # 圣邦股份
    "300373",  # 扬杰科技
    "300666",  # 江丰电子
    "002236",  # 大华股份
    "300623",  # 捷捷微电
    "300349",  # 金卡智能
    "002079",  # 苏州固锝
    "603688",  # 石英股份
    "002119",  # 康强电子
    "603005",  # 晶方科技
    "688002",  # 睿创微纳
    "688099",  # 晶晨股份
    "002185",  # 华天科技
    "600460",  # 士兰微
    "300474",  # 景嘉微
    "300567",  # 精测电子
    "300054",  # 鼎龙股份
    "300398",  # 飞凯材料
    "300327",  # 中颖电子

    # 核心大行业与细分龙头
    "000858",  # 五粮液
    "600809",  # 山西汾酒
    "601100",  # 恒立液压
    "603638",  # 艾迪精密
    "000876",  # 新希望
    "300999",  # 金龙鱼
    "000895",  # 双汇发展
    "300059",  # 东方财富
    "300033",  # 同花顺
    "600030",  # 中信证券
    "601318",  # 中国平安
    "601628",  # 中国人寿
    "601601",  # 中国太保
    "000001",  # 平安银行
    "600036",  # 招商银行
    "002142",  # 宁波银行
    "000002",  # 万科A
    "600048",  # 保利发展
    "601012",  # 隆基绿能
    "601636",  # 旗滨集团
    "002129",  # TCL中环
    "300595",  # 欧普康视
    "600763",  # 通策医疗
    "000333",  # 美的集团
    "000651",  # 格力电器
    "600690",  # 海尔智家
    "002032",  # 苏泊尔
    "600887",  # 伊利股份
    "002460",  # 赣锋锂业
    "002466",  # 天齐锂业
    "300122",  # 智飞生物
    "002007",  # 华兰生物
    "300142",  # 沃森生物
    "600276",  # 恒瑞医药
    "000513",  # 丽珠集团
    "002271",  # 东方雨虹
    "002352",  # 顺丰控股
    "600233",  # 圆通速递
    "000830",  # 鲁西化工
    "600426",  # 华鲁恒升
    "002594",  # 比亚迪
    "601633",  # 长城汽车
    "600031",  # 三一重工
    "000157",  # 中联重科
    "000425",  # 徐工机械
    "688981",  # 中芯国际
    "600547",  # 山东黄金
    "000975",  # 山金国际
    "600988",  # 赤峰黄金
    "600585",  # 海螺水泥
    "000100",  # TCL科技
    "300003",  # 乐普医疗
    "601668",  # 中国建筑
    "601390",  # 中国中铁
    "603799",  # 华友钴业
    "601899",  # 紫金矿业
    "002421",  # 达实智能
    "300223",  # 北京君正
]

_CACHED_ALL_ASHARES: list[str] = []

def _load_all_ashares() -> list[str]:
    """Load cached 5,200+ A-share codes."""
    global _CACHED_ALL_ASHARES
    if _CACHED_ALL_ASHARES:
        return _CACHED_ALL_ASHARES
    
    # Try easy_tdx data dir
    possible_paths = [
        Path(__file__).resolve().parent.parent.parent.parent / "data" / "ashares_universe.json",
        Path("c:/Users/aaron/Documents/stock_data/easy_tdx/data/ashares_universe.json"),
        Path("c:/Users/aaron/Documents/stock_data/stock_quant/data/ashares_universe.json"),
    ]
    for p in possible_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    codes = json.load(f)
                    if isinstance(codes, list) and len(codes) > 1000:
                        _CACHED_ALL_ASHARES = [str(c).zfill(6) for c in codes]
                        logger.info(f"Loaded {len(_CACHED_ALL_ASHARES)} A-share codes from {p}")
                        return _CACHED_ALL_ASHARES
            except Exception as e:
                logger.warning(f"Error loading {p}: {e}")

    # Fallback to core universe
    return CORE_UNIVERSE

def get_universe_symbols(scope: str = "core") -> list[str]:
    """Get stock symbols for the requested universe scope."""
    s = (scope or "core").lower().strip()
    all_stocks = _load_all_ashares()
    
    if s == "core":
        return CORE_UNIVERSE
    elif s in ("hs300", "csi300", "300"):
        # Prioritize core stocks then fill up to 300
        core_set = set(CORE_UNIVERSE)
        rest = [c for c in all_stocks if c not in core_set]
        return (CORE_UNIVERSE + rest)[:300]
    elif s in ("zz500", "csi500", "500"):
        core_set = set(CORE_UNIVERSE)
        rest = [c for c in all_stocks if c not in core_set]
        return (CORE_UNIVERSE + rest)[:500]
    elif s in ("zz1000", "csi1000", "1000"):
        core_set = set(CORE_UNIVERSE)
        rest = [c for c in all_stocks if c not in core_set]
        return (CORE_UNIVERSE + rest)[:1000]
    elif s in ("all", "full", "all_a", "market"):
        return all_stocks
    else:
        return CORE_UNIVERSE

def get_universe_options() -> list[dict[str, Any]]:
    """Return universe descriptions for UI rendering."""
    all_count = len(_load_all_ashares())
    return [
        {
            "id": "core",
            "name": "核心龙头精选",
            "count": len(CORE_UNIVERSE),
            "est_time": "~2-3 秒",
            "badge": "秒级响应",
            "desc": f"东方财富全行业最全核心龙头名单精选 ({len(CORE_UNIVERSE)}只)"
        },
        {
            "id": "hs300",
            "name": "沪深300标的池",
            "count": 300,
            "est_time": "~6 秒",
            "badge": "快速选股",
            "desc": "A 股规模大、流动性好的 300 只最具代表性蓝筹白马"
        },
        {
            "id": "zz500",
            "name": "中证500标的池",
            "count": 500,
            "est_time": "~12 秒",
            "badge": "中盘主力",
            "desc": "聚焦各细分行业高成长、弹性大的优质中盘标的"
        },
        {
            "id": "zz1000",
            "name": "中证1000标的池",
            "count": 1000,
            "est_time": "~25 秒",
            "badge": "活跃小盘",
            "desc": "覆盖中小盘活跃品种，捕捉游资与弹性波段机会"
        },
        {
            "id": "all",
            "name": "全市场全A股",
            "count": all_count,
            "est_time": "后台异步任务",
            "badge": "全量大满贯",
            "desc": "无死角扫描 A 股 5,200+ 标的，多线程后台异步并发计算"
        }
    ]
