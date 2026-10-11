"""申报前数据流：接入、抽取、对齐、判定、解释。

判定只走规则。解释复述判定，不能把「先别申报」改成「可以申报」。
结构参考单证审批流水线：抽取和质量分与最终决定分开。
"""

from __future__ import annotations

from yuexian.documents import render_shipment
from yuexian.extract import extract_document, extract_with_qwen
from yuexian.rules import judge_shipment

STAGES = ("ingest", "extract", "structure", "decide", "explain")


def run_shipment(shipment: dict, threshold: float, use_qwen: bool = False) -> dict:
    documents = render_shipment(shipment)
    trace = []
    trace.append(
        {
            "stage": "ingest",
            "documents": sorted(documents),
            "chars": {name: len(text) for name, text in documents.items()},
        }
    )
    extracted = []
    qwen_note = None
    qwen_status = "disabled" if not use_qwen else "no_document"
    for name, text in documents.items():
        parsed = extract_document(text)
        extracted.append(parsed)
        if use_qwen and name == "bl":
            qwen_note = extract_with_qwen(text)
            if qwen_note is None:
                qwen_status = "not_configured"
            elif (
                isinstance(qwen_note, dict)
                and "error" not in qwen_note
                and isinstance(qwen_note.get("raw"), str)
                and qwen_note["raw"].strip()
            ):
                qwen_status = "response_received"
            else:
                qwen_status = "failed"
    trace.append(
        {
            "stage": "extract",
            "stations": [item["station"] for item in extracted],
            "qwen": qwen_note["source"] if isinstance(qwen_note, dict) and "source" in qwen_note else "off",
            "qwen_status": qwen_status,
        }
    )
    structured = _structure(shipment, extracted)
    trace.append(
        {
            "stage": "structure",
            "weight_points": len(structured["gross_weight_kg"]),
            "ocr_points": sum(
                1 for item in structured["gross_weight_kg"] if item["label"] == "ocr_error"
            ),
        }
    )
    judged = judge_shipment(structured, threshold)
    trace.append({"stage": "decide", "verdict": judged["verdict"], "blocks": len(judged["blocks"])})
    explanation = _explain(judged)
    if explanation["verdict"] != judged["verdict"]:
        raise RuntimeError("解释改写了规则判定")
    trace.append({"stage": "explain", "verdict": explanation["verdict"]})
    return {
        "id": shipment["id"],
        "title": shipment.get("title", ""),
        "documents": documents,
        "trace": trace,
        "judgement": judged,
        "explanation": explanation["text"],
    }


def run_dataset(dataset: dict, use_qwen: bool = False) -> list[dict]:
    threshold = dataset["threshold_gross_weight"]
    return [run_shipment(item, threshold, use_qwen=use_qwen) for item in dataset["shipments"]]


def _structure(shipment: dict, extracted: list[dict]) -> dict:
    merged = {
        "id": shipment["id"],
        "title": shipment.get("title", ""),
        "demo": shipment.get("demo", False),
        "gross_weight_kg": [],
        "container_no": [],
        "seal_no": [],
        "countries": {},
    }
    for item in extracted:
        for field in ("gross_weight_kg", "container_no", "seal_no"):
            merged[field].extend(item["observations"][field])
        for key, value in item["countries"].items():
            merged["countries"][key] = value
    return merged


def _explain(judged: dict) -> dict:
    lines = [judged["headline"]]
    if judged["verdict"] == "send":
        lines.append("装箱毛重与提单一致，柜号和封条只有一版，四国口径分栏。")
    for block in judged["blocks"]:
        lines.append(block["if_send"])
        lines.append(block["action"])
    for issue in judged.get("pending", []):
        lines.append(issue["message"])
    if judged["ocr_ignored"]:
        lines.append(f"已忽略 {judged['ocr_ignored']} 处抽取误差，不计入改写。")
    lines.append("以上句子只复述规则结果。")
    return {"verdict": judged["verdict"], "text": " ".join(lines)}
