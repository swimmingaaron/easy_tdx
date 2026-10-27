"""同步通达信全市场 128 个标准行业板块及成分股，生成持久化行业知识库 data/industry_universe.json
"""
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from easy_tdx import MacClient, BoardType

INDUSTRY_CATEGORY_MAPPING = {
    "信息技术与芯片半导体": [
        "半导体", "消费电子", "元器件", "通信设备", "软件服务", "IT设备", "光学光电",
        "其他电子", "通信工程", "电信服务", "数字媒体", "云服务", "产业互联网"
    ],
    "新能源与电力设备": [
        "电池", "光伏设备", "风电设备", "电网设备", "电机制造", "其他发电设备", "电力"
    ],
    "医药生物与医疗健康": [
        "化学制药", "中药", "生物制品", "医疗器械", "医疗服务", "医药商业", "医疗美容", "动物保健"
    ],
    "大消费与食品饮料": [
        "酿酒", "饮料乳品", "食品加工", "休闲食品", "调味品", "养殖业", "农产品加工",
        "种植业", "渔业", "林业", "白色家电", "小家电", "黑色家电", "厨卫电器", "家电零部件",
        "一般零售", "专业连锁", "电子商务", "贸易"
    ],
    "汽车与交通运输": [
        "乘用车", "商用车", "汽车零部件", "汽车服务", "摩托车及其他",
        "航空机场", "航运港口", "公路铁路", "物流"
    ],
    "金融与地产服务": [
        "证券", "全国性银行", "地方性银行", "保险", "多元金融",
        "房地产开发", "房产服务", "商业物业经营"
    ],
    "高端装备与军工制造": [
        "航空装备", "航天装备", "军工电子", "地面兵装", "航海装备", "轨交设备",
        "自动化设备", "工程机械", "专用设备", "通用设备"
    ],
    "周期资源与基础化工": [
        "煤炭开采", "焦炭加工", "油气开采", "石油化工", "油服工程",
        "工业金属", "稀有金属", "贵金属", "能源金属", "特钢", "普钢", "冶钢原料",
        "化学原料", "化学制品", "农用化工", "电子化学品", "化纤", "塑料", "橡胶", "非金属材料", "金属新材料"
    ],
    "建筑建材与公共环保": [
        "基础建设", "房屋建设", "专业工程", "装饰建材", "水泥", "玻璃玻纤", "装修装饰", "工程咨询服务",
        "燃气", "水务", "环境治理", "环保设备", "环境监测"
    ],
    "文娱教育与轻工生活": [
        "游戏", "影视院线", "出版业", "广播电视", "广告营销", "旅游", "酒店餐饮", "教育培训", "体育", "专业服务",
        "服装家纺", "纺织制造", "家居用品", "轻工机械", "造纸", "包装印刷", "日用化工", "饰品", "文娱用品", "综合类"
    ]
}


def get_category_for_industry(ind_name: str) -> str:
    for cat, names in INDUSTRY_CATEGORY_MAPPING.items():
        if ind_name in names:
            return cat
    for cat, names in INDUSTRY_CATEGORY_MAPPING.items():
        for n in names:
            if n in ind_name or ind_name in n:
                return cat
    return "其他行业"


def sync_all_industries() -> Dict[str, Any]:
    print("[1/3] 正在从通达信主站拉取全市场行业板块列表...", flush=True)
    t0 = time.time()
    with MacClient.from_best_host() as c:
        df_boards = c.get_board_list(BoardType.HY, count=300)
        board_list = []
        for _, row in df_boards.iterrows():
            b_code = str(row["code"]).strip()
            b_name = str(row["name"]).strip()
            if b_code and b_name:
                board_list.append({"code": b_code, "name": b_name})

        print(f"[OK] 成功获取 {len(board_list)} 个标准行业板块 (耗时 {time.time()-t0:.1f}s)", flush=True)
        print("[2/3] 正在使用极速链路拉取各行业成分股...", flush=True)

        industries_dict = {}
        stock_to_industry = {}

        t_members = time.time()
        for idx, b_info in enumerate(board_list, 1):
            code = b_info["code"]
            name = b_info["name"]
            cat = get_category_for_industry(name)
            try:
                df = c.get_board_members(code, count=1000)
                symbols = [str(r["code"]).zfill(6) for _, r in df.iterrows()] if df is not None and not df.empty else []
            except Exception as e:
                symbols = []

            industries_dict[code] = {
                "code": code,
                "name": name,
                "category": cat,
                "count": len(symbols),
                "symbols": symbols,
            }
            for s in symbols:
                if s not in stock_to_industry:
                    stock_to_industry[s] = {"code": code, "name": name, "category": cat}

            if idx % 20 == 0 or idx == len(board_list):
                print(f"  -> 已完成 {idx}/{len(board_list)} 个行业板块 (耗时 {time.time()-t_members:.1f}s)", flush=True)

    sorted_industries = sorted(industries_dict.values(), key=lambda x: (x["category"], -x["count"]))

    category_summary = {}
    for ind in sorted_industries:
        cat = ind["category"]
        if cat not in category_summary:
            category_summary[cat] = {"category": cat, "industry_count": 0, "stock_count": 0, "industries": []}
        category_summary[cat]["industry_count"] += 1
        category_summary[cat]["stock_count"] += ind["count"]
        category_summary[cat]["industries"].append({
            "code": ind["code"],
            "name": ind["name"],
            "count": ind["count"]
        })

    payload = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_industries": len(sorted_industries),
        "total_unique_stocks": len(stock_to_industry),
        "categories": list(category_summary.values()),
        "industries": sorted_industries,
        "stock_to_industry": stock_to_industry,
    }

    print("[3/3] 正在持久化到 data/industry_universe.json...", flush=True)
    out_path = Path("data/industry_universe.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 清理中间临时文件
    tmp_raw = Path("data/industry_boards_raw.json")
    if tmp_raw.exists():
        tmp_raw.unlink()

    print(f"[OK] 同步完成！共定义 {len(sorted_industries)} 个行业板块，覆盖 {len(stock_to_industry)} 只 A 股！总耗时: {time.time()-t0:.1f}s", flush=True)
    return payload


if __name__ == "__main__":
    sync_all_industries()
