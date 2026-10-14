"""按输入类型用规则选择处理路径。模型不参与选路。"""

from __future__ import annotations

# 认得出、但本项目不实现解析器的类型。调度结果是回退待核验，不假装抽出字段。
UNSUPPORTED = frozenset(
    {
        "pdf",
        "image",
        "png",
        "jpg",
        "jpeg",
        "certificate",
        "hs",
        "application/pdf",
    }
)

RULES = (
    {"type": "text/documents", "handler": "run_documents"},
    {"type": "text/form", "handler": "extract_document"},
    {"type": "json/shipment", "handler": "structure_record"},
    {"type": "unsupported", "handler": "review_fallback"},
)

# 回退只改变这一票的入口，不改已经成立的规则结论。
FALLBACK = {
    "unsupported_type": "{kind} 不在本项目解析范围内，已回退为待核验",
    "noncompliant": "输入不合规或处理失败，已回退为待核验",
    "missing": "单证缺少可抽取栏位，已回退为待核验",
}


def classify(item) -> str:
    if isinstance(item, str):
        return "text/form"
    if not isinstance(item, dict):
        return "unsupported"
    kind = str(item.get("input_type") or item.get("file_type") or "").strip().lower()
    if kind in {"txt", "text", "form", "text/form"}:
        return "text/form"
    if kind in UNSUPPORTED:
        return "unsupported"
    if "documents" in item:
        return "text/documents"
    if "text" in item and "gross_weight_kg" not in item:
        return "text/form"
    if "gross_weight_kg" in item or ("id" in item and "countries" in item):
        return "json/shipment"
    return "unsupported"


def rule_for(item) -> dict:
    kind = classify(item)
    matched = next(rule for rule in RULES if rule["type"] == kind)
    return {"type": kind, "handler": matched["handler"]}


def review_fallback(item, message: str) -> dict:
    """不合规或未接入的类型不进入判定比较，整票回退为待核验。"""
    if isinstance(item, dict):
        shipment_id = str(item.get("id") or "UNKNOWN")
        title = str(item.get("title") or "")
    else:
        shipment_id = "UNKNOWN"
        title = ""
    return {
        "id": shipment_id,
        "title": title,
        "demo": False,
        "verdict": "review",
        "headline": "资料待核验",
        "blocks": [],
        "pending": [{"field": "input", "station": "dispatch", "message": message}],
        "ocr_ignored": 0,
    }
