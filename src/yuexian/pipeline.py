"""申报前数据流：接入、按类型调度、预处理、抽取、对齐、判定、解释。

判定只走规则。解释复述判定，不能把「先别申报」改成「可以申报」。
不同类型只改变进入字段之前的路径。未接入的类型回退为待核验，不进入比较。
"""

from __future__ import annotations

import copy
import time
from concurrent.futures import ThreadPoolExecutor

from yuexian.dispatch import FALLBACK, classify, review_fallback, rule_for
from yuexian.documents import render_shipment
from yuexian.extract import extract_document, extract_with_qwen
from yuexian.preprocess import preprocess_text
from yuexian.rules import judge_shipment

STAGES = ("ingest", "dispatch", "preprocess", "extract", "structure", "decide", "explain")


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
    route = rule_for(shipment)
    prepared = []
    dropped = 0
    fallbacks = []
    for name, text in documents.items():
        cleaned = preprocess_text(text)
        dropped += cleaned["dropped_noise"]
        if cleaned["fallback"] != "none":
            fallbacks.append({"document": name, "fallback": cleaned["fallback"]})
        prepared.append((name, cleaned["text"]))
    trace.append(
        {
            "stage": "dispatch",
            "rule": "text/form",
            "handler": "extract_document",
            "source": route["type"],
        }
    )
    trace.append({"stage": "preprocess", "dropped_noise": dropped, "fallbacks": fallbacks})
    extracted = []
    qwen_note = None
    qwen_status = "disabled" if not use_qwen else "no_document"
    for name, text in prepared:
        if not text.strip():
            extracted.append(_blank_parse(shipment["id"], name))
            continue
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
    explanation["text"] += " " + _intake_note("text/form", dropped, fallbacks)
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


def run_input(item, threshold: float, use_qwen: bool = False) -> dict:
    """按类型调度。未接入类型和不合规输入回退为待核验，不抛给调用方。"""
    try:
        route = rule_for(item)
        if route["type"] == "text/documents":
            # 延迟导入：intake复用本模块结构与解释函数。
            from yuexian.intake import run_documents
            return run_documents(item,threshold)
        if route["handler"] == "review_fallback":
            kind = _kind_label(item, route)
            return _fallback_result(item, FALLBACK["unsupported_type"].format(kind=kind), route)
        if route["type"] == "text/form" and not isinstance(item, dict):
            return _run_text(str(item), threshold)
        if route["type"] == "text/form" and isinstance(item, dict) and "gross_weight_kg" not in item:
            return _run_text(str(item.get("text") or ""), threshold, str(item.get("id") or ""))
        return run_shipment(item, threshold, use_qwen=use_qwen)
    except Exception:
        return _fallback_result(item, FALLBACK["noncompliant"], {"type": "unsupported", "handler": "review_fallback"})


def run_batch(items: list, threshold: float, workers: int = 4) -> list[dict]:
    """多票异步处理。每票仍走同一套调度和规则，返回顺序与输入一致。"""
    width = max(1, workers)

    def one(item):
        return run_input(item, threshold)

    with ThreadPoolExecutor(max_workers=width) as pool:
        return list(pool.map(one, items))


def ballast_items(dataset: dict, copies: int = 40, bad_every: int = 7) -> list:
    """样例重复扩成一批，并按固定间隔夹入未接入类型，用来压异步回退。"""
    items: list = []
    shipments = list(dataset["shipments"])
    for index, shipment in enumerate(shipments * max(1, copies)):
        items.append(copy.deepcopy(shipment))
        if bad_every > 0 and (index + 1) % bad_every == 0:
            items.append({"id": f"BALLAST-{index}", "input_type": "pdf", "title": "压舱未接入文件"})
    return items


def run_ballast(dataset: dict, copies: int = 40, workers: int = 4, bad_every: int = 7) -> dict:
    """异步跑一批混合输入。样例结论必须与同步判定一致，未接入类型必须回退。"""
    threshold = dataset["threshold_gross_weight"]
    items = ballast_items(dataset, copies=copies, bad_every=bad_every)
    expected = {
        shipment["id"]: run_shipment(shipment, threshold)["judgement"]["verdict"]
        for shipment in dataset["shipments"]
    }
    started = time.perf_counter()
    ran = run_batch(items, threshold, workers=workers)
    elapsed = time.perf_counter() - started
    mismatches = 0
    fallbacks = 0
    for source, result in zip(items, ran):
        verdict = result["judgement"]["verdict"]
        if classify(source) == "unsupported":
            fallbacks += 1
            if verdict != "review" or result["trace"][0]["handler"] != "review_fallback":
                mismatches += 1
        elif verdict != expected[source["id"]]:
            mismatches += 1
    return {
        "count": len(ran),
        "workers": max(1, workers),
        "fallbacks": fallbacks,
        "mismatches": mismatches,
        "seconds": round(elapsed, 4),
        "stable": mismatches == 0 and len(ran) == len(items),
    }


def _run_text(text: str, threshold: float, shipment_id: str = "") -> dict:
    cleaned = preprocess_text(text)
    parsed = extract_document(cleaned["text"]) if cleaned["text"].strip() else _blank_parse(shipment_id, "unknown")
    shipment = {
        "id": shipment_id or parsed.get("shipment_id") or "TEXT",
        "title": "",
        "demo": False,
        "gross_weight_kg": parsed["observations"]["gross_weight_kg"],
        "container_no": parsed["observations"]["container_no"],
        "seal_no": parsed["observations"]["seal_no"],
        "countries": parsed["countries"],
    }
    judged = judge_shipment(shipment, threshold)
    if cleaned["fallback"] == "missing" and judged["verdict"] == "send":
        judged = review_fallback(shipment, FALLBACK["missing"])
    text_fallbacks = [] if cleaned["fallback"] == "none" else [{"document": "text", "fallback": cleaned["fallback"]}]
    explanation = _explain(judged)
    explanation["text"] += " " + _intake_note("text/form", cleaned["dropped_noise"], text_fallbacks)
    return {
        "id": shipment["id"],
        "title": "",
        "documents": {"text": text},
        "trace": [
            {"stage": "dispatch", "rule": "text/form", "handler": "extract_document", "source": "text/form"},
            {
                "stage": "preprocess",
                "dropped_noise": cleaned["dropped_noise"],
                "fallbacks": text_fallbacks,
            },
            {"stage": "decide", "verdict": judged["verdict"], "blocks": len(judged["blocks"])},
        ],
        "judgement": judged,
        "explanation": explanation["text"],
    }


def _fallback_result(item, message: str, route: dict | None = None) -> dict:
    judged = review_fallback(item, message)
    explanation = _explain(judged)
    return {
        "id": judged["id"],
        "title": judged["title"],
        "documents": {},
        "trace": [
            {
                "stage": "dispatch",
                "rule": (route or {}).get("type", "unsupported"),
                "handler": "review_fallback",
                "source": (route or {}).get("type", "unsupported"),
            },
            {"stage": "decide", "verdict": "review", "blocks": 0},
        ],
        "judgement": judged,
        "explanation": explanation["text"],
    }


def _kind_label(item, route: dict) -> str:
    if isinstance(item, dict):
        return str(item.get("input_type") or item.get("file_type") or route["type"])
    return route["type"]


def _blank_parse(shipment_id: str, station: str) -> dict:
    return {
        "shipment_id": shipment_id,
        "station": station,
        "observations": {"gross_weight_kg": [], "container_no": [], "seal_no": []},
        "countries": {},
    }


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


def _intake_note(rule: str, dropped: int, fallbacks: list[dict]) -> str:
    note = f"调度规则 {rule}。预处理去掉 {dropped} 行噪声。"
    if fallbacks:
        detail = "、".join(f"{item['document']} {item['fallback']}" for item in fallbacks)
        note += f"回退 {detail}。"
    return note + "结论只来自规则。"


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
