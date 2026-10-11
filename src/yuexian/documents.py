"""把金标准样例渲染成可抽取的单证文本。

版式参考报关台对单时并排看的装箱单和提单，不使用企业真实单据。
"""

from __future__ import annotations

from yuexian.rules import value_at


def render_shipment(shipment: dict) -> dict[str, str]:
    docs = {
        "packing": _doc(shipment, "packing", "PACKING_LIST"),
        "bl": _doc(shipment, "bl", "BILL_OF_LADING"),
    }
    manifest = _manifest(shipment)
    if manifest:
        docs["manifest"] = manifest
    # 定位改写必须有真实提供的历史观测，不能从两张单证猜出生站。
    for station, doc_type in (("booking", "BOOKING"), ("declaration", "DECLARATION")):
        if any(value_at(shipment.get(field, []), station) is not None
               for field in ("gross_weight_kg", "container_no", "seal_no")):
            docs[station] = _doc(shipment, station, doc_type)
    return docs


TITLES = {
    "BOOKING": "订舱记录 BOOKING",
    "DECLARATION": "报关记录 DECLARATION",
    "PACKING_LIST": "装箱单 PACKING LIST",
    "BILL_OF_LADING": "提单 BILL OF LADING",
    "MANIFEST": "舱单 MANIFEST",
}


def _doc(shipment: dict, station: str, doc_type: str) -> str:
    weight = value_at(shipment.get("gross_weight_kg", []), station)
    container = value_at(shipment.get("container_no", []), station)
    seal = value_at(shipment.get("seal_no", []), station)
    lines = [
        TITLES[doc_type],
        "合成样例，非正式海关单证。",
        f"单证站点：{station}",
        f"票号：{shipment['id']}",
        f"货名：{shipment.get('title', '')}",
    ]
    if weight is not None:
        lines.append(f"毛重（公斤）：{weight}")
    noisy = _ocr_noise(shipment.get("gross_weight_kg", []), station)
    if noisy is not None:
        lines.append(f"扫描毛重（公斤）：{noisy}")
    if container:
        lines.append(f"柜号：{container}")
    if seal:
        lines.append(f"封条号：{seal}")
    lines.extend(_country_lines(shipment))
    return "\n".join(lines) + "\n"


def _manifest(shipment: dict) -> str | None:
    if not any(value_at(shipment.get(field, []), "manifest") is not None
               for field in ("gross_weight_kg", "container_no", "seal_no")):
        return None
    return _doc(shipment, "manifest", "MANIFEST")


def _ocr_noise(observations: list[dict], station: str):
    hits = [
        item
        for item in observations
        if item.get("station") == station and item.get("label") == "ocr_error"
    ]
    if not hits:
        return None
    return hits[-1]["value"]


def _country_lines(shipment: dict) -> list[str]:
    countries = shipment.get("countries") or {}
    if not countries:
        return []
    collapsed = countries.get("collapsed_value")
    if collapsed:
        return [
            f"国家：{collapsed}",
            f"贸易国：{countries.get('trade', '')}",
            f"原产国：{countries.get('origin', '')}",
            f"启运国：{countries.get('departure', '')}",
            f"最终目的国：{countries.get('destination', '')}",
        ]
    return [
        f"贸易国：{countries.get('trade', '')}",
        f"启运国：{countries.get('departure', '')}",
        f"原产国：{countries.get('origin', '')}",
        f"最终目的国：{countries.get('destination', '')}",
    ]
