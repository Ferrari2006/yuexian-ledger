"""申报前规则。模型不得改写这里的判定。"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

from yuexian.weights import parse_weight

STATION_ORDER = ["booking", "packing", "bl", "manifest", "declaration"]
BIRTH_TARGETS = {"packing", "manifest"}
STATION_LABELS = {
    "booking": "订舱",
    "packing": "装箱单",
    "bl": "提单",
    "manifest": "舱单",
    "declaration": "报关草稿",
}


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


def field_timeline(shipment: dict, field: str) -> list[dict]:
    """按业务站点给出字段的可视化证据链，不把 OCR 误差当作业务改写。"""
    observations = shipment.get(field, [])
    previous = None
    points = []
    for station in STATION_ORDER:
        value = value_at(observations, station)
        changed = value is not None and previous is not None and value != previous
        points.append(
            {
                "station": station,
                "label": STATION_LABELS[station],
                "value": value,
                "changed": changed,
            }
        )
        if value is not None:
            previous = value
    return points


def resolution_options(judged: dict) -> list[dict]:
    """给当前未解决的阻塞项列出可选的人工确认动作。"""
    options = []
    for block in judged["blocks"]:
        kind = block["kind"]
        if kind == "gross_weight":
            options.extend(
                [
                    {"token": "gross_weight:packing", "label": "以装箱单毛重为准"},
                    {"token": "gross_weight:bl", "label": "以提单毛重为准"},
                ]
            )
        elif kind in {"container_no", "seal_no"}:
            title = block["title"]
            options.extend(
                [
                    {"token": f"{kind}:bl", "label": f"以提单{title}为准"},
                    {"token": f"{kind}:manifest", "label": f"以舱单{title}为准"},
                ]
            )
        elif kind == "countries":
            options.append({"token": "countries:split", "label": "拆分贸易国、启运国、原产国和目的国"})
    return options


def resolve_shipment(shipment: dict, token: str) -> dict:
    """返回一份整改后的副本，原始样例和其业务轨迹保持不变。"""
    try:
        kind, source = token.split(":", 1)
    except ValueError as exc:
        raise ValueError(f"无效整改动作：{token}") from exc

    resolved = deepcopy(shipment)
    if kind == "countries" and source == "split":
        resolved.setdefault("countries", {}).pop("collapsed_value", None)
        return resolved

    fields = {
        "gross_weight": ("gross_weight_kg", ("packing", "bl", "manifest", "declaration")),
        "container_no": ("container_no", ("bl", "manifest")),
        "seal_no": ("seal_no", ("bl", "manifest")),
    }
    if kind not in fields:
        raise ValueError(f"不支持的整改字段：{kind}")
    field, stations = fields[kind]
    if source not in stations:
        raise ValueError(f"{kind} 不能以 {source} 为准")
    authoritative = value_at(resolved.get(field, []), source)
    if authoritative is None:
        raise ValueError(f"{source} 没有可用的 {kind} 值")
    for station in stations:
        if station != source:
            _set_rewrite_value(resolved[field], station, authoritative)
    return resolved


def _set_rewrite_value(observations: list[dict], station: str, value) -> None:
    for item in reversed(observations):
        if item.get("station") == station and item.get("label") == "rewrite":
            item["value"] = value
            return
    observations.append({"station": station, "value": value, "label": "rewrite"})


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
    threshold_ok = (
        not isinstance(threshold, bool) and isinstance(threshold, (int, float))
        and 0 <= threshold < 1 and math.isfinite(threshold)
    )
    if not threshold_ok:
        pending.append({"field": "threshold", "station": "rules",
                        "message": "毛重偏差阈值无效，须为0到1之间的有限数值，请核验规则配置"})
    normalized_weight_obs = [
        {**item, "value": parse_weight(item.get("value"))}
        for item in weight_obs
    ]
    weight_birth = birth_station(normalized_weight_obs)
    if threshold_ok and gap is not None and gap > threshold:
        blocks.append(
            {
                "kind": "gross_weight",
                "birth_station": weight_birth,
                "packing_kg": packing,
                "bl_kg": bl,
                "gap": round(gap, 4),
                "action": "改提单毛重，或改装箱单后再发",
                "if_send": f"毛重偏差超过当前阈值 {threshold:.1%}，自动比对可能退单",
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
    review_count = sum(1 for item in judged if item["verdict"] == "review")
    hold_count = sum(1 for item in judged if item["verdict"] == "hold")
    send_count = sum(1 for item in judged if item["verdict"] == "send")
    return {
        "shipments": judged,
        "birth_station_ratio": round(ratio, 4),
        "birth_station_hit": birth_hit,
        "birth_station_total": len(rewrite_births),
        "country_mix_count": country_errors,
        "weight_hold_count": weight_holds,
        "review_count": review_count,
        "hold_count": hold_count,
        "send_count": send_count,
        "threshold_note": dataset["threshold_note"],
    }
