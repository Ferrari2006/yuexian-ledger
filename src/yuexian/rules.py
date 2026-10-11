"""申报前规则。模型不得改写这里的判定。"""

from __future__ import annotations

import json
from pathlib import Path

from yuexian.weights import parse_weight

STATION_ORDER = ["booking", "packing", "bl", "manifest", "declaration"]
BIRTH_TARGETS = {"packing", "manifest"}


def load_dataset(path: Path | None = None) -> dict:
    if path is None:
        path = Path(__file__).resolve().parents[2] / "data" / "shipments.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _rewrites(observations: list[dict]) -> list[dict]:
    return [item for item in observations if item.get("label") == "rewrite"]


def birth_station(observations: list[dict]) -> str | None:
    """第一次相对上一站发生变化的站点。抽取误差不参与。"""
    latest = {item["station"]: item for item in _rewrites(observations)}
    chosen = [latest[station] for station in STATION_ORDER if station in latest]
    previous = None
    for item in chosen:
        if previous is not None and item["value"] != previous:
            return item["station"]
        previous = item["value"]
    return None


def value_at(observations: list[dict], station: str):
    hits = [item for item in _rewrites(observations) if item["station"] == station]
    if not hits:
        return None
    return hits[-1]["value"]


def weight_gap(packing, bl) -> float | None:
    packing, bl = parse_weight(packing), parse_weight(bl)
    if packing is None or bl is None or packing <= 0 or bl <= 0:
        return None
    return abs(packing - bl) / abs(bl)


def country_mixed(countries: dict) -> bool:
    collapsed = countries.get("collapsed_value")
    if not collapsed:
        return False
    return collapsed == countries.get("origin") and countries.get("trade") != countries.get("origin")


def judge_shipment(shipment: dict, threshold: float) -> dict:
    blocks = []
    pending = []
    weight_obs = shipment.get("gross_weight_kg", [])
    packing = parse_weight(value_at(weight_obs, "packing"))
    bl = parse_weight(value_at(weight_obs, "bl"))
    for station, value, title in (("packing", packing, "装箱单"), ("bl", bl, "提单")):
        if value is None or value <= 0:
            pending.append({"field": "gross_weight_kg", "station": station,
                            "message": f"{title}毛重缺失或不是有效的正数公斤值，请核验原文"})
    gap = weight_gap(packing, bl)
    normalized_weight_obs = [
        {**item, "value": parse_weight(item.get("value"))}
        for item in weight_obs
    ]
    weight_birth = birth_station(normalized_weight_obs)
    if gap is not None and gap > threshold:
        blocks.append(
            {
                "kind": "gross_weight",
                "birth_station": weight_birth,
                "packing_kg": packing,
                "bl_kg": bl,
                "gap": round(gap, 4),
                "action": "改提单毛重，或改装箱单后再发",
                "if_send": "毛重偏差超过约 3%，自动比对可能退单",
            }
        )

    for field, title in (("container_no", "柜号"), ("seal_no", "封条号")):
        obs = shipment.get(field, [])
        left = value_at(obs, "bl")
        right = value_at(obs, "manifest")
        left_ok = isinstance(left, str) and bool(left.strip())
        right_ok = isinstance(right, str) and bool(right.strip())
        for station, ok, doc_title in (("bl", left_ok, "提单"), ("manifest", right_ok, "舱单")):
            if not ok:
                pending.append({"field": field, "station": station,
                                "message": f"{doc_title}{title}缺失或无效，请核验原文"})
        if left_ok and right_ok and left != right:
            blocks.append(
                {
                    "kind": field,
                    "birth_station": birth_station(obs),
                    "title": title,
                    "bl": left,
                    "manifest": right,
                    "action": f"先改{title}，提单和舱单必须是同一版",
                    "if_send": f"{title}不一致，自动比对可能退单",
                }
            )

    if country_mixed(shipment.get("countries", {})):
        countries = shipment["countries"]
        blocks.append(
            {
                "kind": "countries",
                "birth_station": None,
                "action": "把贸易国、启运国、原产国、最终目的国分成四栏再发",
                "if_send": "四国口径被写成原产国一格，优惠原产地可能判错",
                "detail": countries,
            }
        )

    countries = shipment.get("countries", {})
    for field, title in (("trade", "贸易国"), ("departure", "启运国"),
                         ("origin", "原产国"), ("destination", "最终目的国")):
        value = countries.get(field)
        if not isinstance(value, str) or not value.strip():
            pending.append({"field": field, "station": "countries",
                            "message": f"{title}缺失或无效，请分别核验国家字段"})

    hold = len(blocks) > 0
    verdict = "hold" if hold else ("review" if pending else "send")
    return {
        "id": shipment["id"],
        "title": shipment.get("title", ""),
        "demo": bool(shipment.get("demo")),
        "verdict": verdict,
        "headline": {"hold": "先别申报", "review": "资料待核验", "send": "可以申报"}[verdict],
        "blocks": blocks,
        "pending": pending,
        "ocr_ignored": sum(1 for item in weight_obs if item.get("label") == "ocr_error"),
    }


def score(dataset: dict) -> dict:
    threshold = dataset["threshold_gross_weight"]
    judged = [judge_shipment(item, threshold) for item in dataset["shipments"]]
    rewrite_births = []
    for shipment in dataset["shipments"]:
        for field in ("gross_weight_kg", "container_no", "seal_no"):
            birth = birth_station(shipment.get(field, []))
            if birth:
                rewrite_births.append(birth)
    birth_hit = sum(1 for station in rewrite_births if station in BIRTH_TARGETS)
    country_errors = sum(1 for item in dataset["shipments"] if country_mixed(item.get("countries", {})))
    weight_holds = sum(
        1
        for item in judged
        if any(block["kind"] == "gross_weight" for block in item["blocks"])
    )
    ratio = (birth_hit / len(rewrite_births)) if rewrite_births else 0
    return {
        "shipments": judged,
        "birth_station_ratio": round(ratio, 4),
        "birth_station_hit": birth_hit,
        "birth_station_total": len(rewrite_births),
        "country_mix_count": country_errors,
        "weight_hold_count": weight_holds,
        "threshold_note": dataset["threshold_note"],
    }
