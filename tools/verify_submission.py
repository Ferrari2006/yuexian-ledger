"""交稿自检：验证 demo 的数字和完整流水线输出与实时复算一致。

`README` 与 `docs/提交清单.md` 都声称「页脚三个数由规则对全部样例复算，
不是手填的」。这个声称必须在交稿前机器验证 —— 评审现场会打开页面，
也会当场问「这些数怎么来的」。

本脚本从 `demo/index.html` 里解析内嵌 DATA 和 FLOWS，与规则及抽取流水线
的实时复算逐项比对，任何一项漂移即退出码 1。

    python tools/verify_submission.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yuexian.rules import load_dataset, score  # noqa: E402
from yuexian.pipeline import run_dataset  # noqa: E402

DEMO = ROOT / "demo" / "index.html"

# 页脚展示的统计量 -> 必须与规则复算逐字相等
CHECKED = (
    "birth_station_ratio",
    "birth_station_hit",
    "birth_station_total",
    "country_mix_count",
    "weight_hold_count",
)


def demo_payload(name: str):
    if not DEMO.exists():
        raise SystemExit(f"缺少 {DEMO}，先跑 python -m yuexian.build_demo")
    html = DEMO.read_text(encoding="utf-8")
    match = re.search(r"const " + re.escape(name) + r" = (.*?);\s*\n", html, re.S)
    if not match:
        raise ValueError(f"demo/index.html 里找不到内嵌的 {name}")
    return json.loads(match.group(1))


def demo_data() -> dict:
    return demo_payload("DATA")


def main() -> int:
    try:
        data = demo_data()
        flows = demo_payload("FLOWS")
        if not isinstance(data, dict):
            raise ValueError("DATA 必须为对象")
    except (ValueError, OSError) as exc:
        print(f"交稿自检未通过：{exc}")
        return 1
    dataset = load_dataset()
    authoritative = score(dataset)
    expected_flows = run_dataset(dataset)

    print("demo 页脚数字 vs 规则复算")
    print("-" * 52)
    failures: list[str] = []
    for key in CHECKED:
        shown, expected = data.get(key), authoritative.get(key)
        try:
            ok = shown is not None and not isinstance(shown, bool) and abs(float(shown) - float(expected)) < 1e-9
        except (TypeError, ValueError, OverflowError):
            ok = False
        print(f"{key:24}{str(shown):>10}{str(expected):>10}  {'一致' if ok else '不一致'}")
        if not ok:
            failures.append(f"{key}: 页面 {shown!r} vs 规则 {expected!r}")

    # 主演示票必须是「先别申报」，这是清单第一条
    shipments = data.get("shipments")
    if shipments != [flow["judgement"] for flow in expected_flows]:
        failures.append("页面逐票判定与抽取流水线复算不一致，请重新构建 demo")
    expected_page_flows = {
        flow["id"]: {key: flow[key] for key in ("documents", "trace", "explanation")}
        for flow in expected_flows
    }
    if flows != expected_page_flows:
        failures.append("页面单证、轨迹或解释与抽取流水线复算不一致，请重新构建 demo")
    hero = next((s for s in shipments if isinstance(s, dict) and s.get("demo")), None) if isinstance(shipments, list) else None
    if hero is None:
        failures.append("没有标记 demo 的主演示票")
    elif hero.get("headline") != "先别申报":
        failures.append(f"主演示票第一眼不是「先别申报」：{hero.get('headline')!r}")

    print("-" * 52)
    if failures:
        print("交稿自检未通过：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("交稿自检通过：页脚数字、逐票判定、单证、轨迹和解释均与复算一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
