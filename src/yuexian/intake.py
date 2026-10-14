"""有边界的本地文本单证接入。保留原文与行号，不生成或补写业务字段。"""
from __future__ import annotations

from yuexian.extract import (
    COUNTRY_KEYS, FIELD_LINE, ID_KEYS, SHIPMENT_KEYS, STATION_KEYS,
    WEIGHT_KEYS, extract_document,
)
from yuexian.pipeline import _explain, _structure
from yuexian.rules import judge_shipment
from yuexian.weights import parse_weight

STATIONS = frozenset({"booking", "packing", "bl", "manifest", "declaration"})
MAX_TEXT = 200_000


def run_documents(bundle: dict, threshold: float = .03) -> dict:
    """bundle={id, documents:[{name, station, text}]}；语法错误显式抛 ValueError。

    不认识的业务字段不会成为证据；识别字段有冲突时进入待核验。
    """
    if not isinstance(bundle, dict) or set(bundle)-{"id", "title", "documents"}:
        raise ValueError("单证包必须是仅含 id、title、documents 的对象")
    shipment_id = bundle.get("id")
    documents = bundle.get("documents")
    if not isinstance(shipment_id, str) or not shipment_id.strip():
        raise ValueError("id 必须是非空票号")
    if not isinstance(documents, list) or not 1 <= len(documents) <= 10:
        raise ValueError("documents 必须包含1到10份文本单证")
    if not isinstance(bundle.get("title", ""), str):
        raise ValueError("title 必须是文本")
    issues, evidence, parsed_documents, originals = [], [], [], {}
    country_values = {}
    names, stations = set(), set()

    def issue(field, station, message):
        issues.append({"field":field, "station":station, "message":message})

    for document in documents:
        if not isinstance(document, dict) or set(document) != {"name", "station", "text"}:
            raise ValueError("每份单证必须且只能包含 name、station、text")
        name, station, text = (document[k] for k in ("name", "station", "text"))
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("单证 name 必须非空且不重复")
        if not isinstance(station, str) or station not in STATIONS:
            raise ValueError("station 不在支持的单证站点中")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise ValueError("text 必须为不超过200000字符的原文")
        names.add(name)
        if station in stations:
            issue("station",station,f"同一站点 {station} 提供多份单证，请确认有效版本")
        stations.add(station)
        originals[name] = text
        parsed = extract_document(text)
        seen = {}
        for line_number, raw in enumerate(text.splitlines(),1):
            matched = FIELD_LINE.match(raw.strip())
            if not matched:
                continue
            noisy, key, value = matched.group(1), matched.group(2).strip(), matched.group(3).strip()
            if key in STATION_KEYS:
                field = "station"
                if value != station:
                    issue(field,station,f"{name}:{line_number} 原文站点与单证包声明不一致")
            elif key in SHIPMENT_KEYS:
                field = "shipment_id"
                if value != shipment_id:
                    issue(field,station,f"{name}:{line_number} 原文票号与当前票号不一致，禁止混票放行")
            else:
                field = WEIGHT_KEYS.get(key) or ID_KEYS.get(key) or COUNTRY_KEYS.get(key)
            if not field:
                continue
            evidence.append({"document":name, "station":station, "line":line_number,
                             "field":field, "raw":raw, "value":value,
                             "label":"ocr_error" if noisy or key.startswith("扫描") else "rewrite"})
            if noisy or key.startswith("扫描"):
                continue
            canonical = parse_weight(value) if field == "gross_weight_kg" else value
            if field in seen and seen[field] != canonical:
                issue(field,station,f"{name}:{line_number} 同一字段存在多个不同值，请核验原文版本")
            seen[field] = canonical
            if key in COUNTRY_KEYS:
                if field in country_values and country_values[field] != value:
                    issue(field,station,f"{name}:{line_number} 国家字段与其他单证不一致，请核验")
                country_values[field] = value
        if "shipment_id" not in seen:
            issue("shipment_id",station,f"{name} 缺少原文票号，请核验归票依据")
        # 单证包声明站点作为无站点文本的元数据；冲突已经记录，不静默放行。
        for values in parsed["observations"].values():
            for observation in values:
                observation["station"] = station
        parsed["station"] = station
        parsed_documents.append(parsed)
    structured = _structure({"id":shipment_id,"title":bundle.get("title", "")}, parsed_documents)
    judgement = judge_shipment(structured,threshold)
    judgement["pending"].extend(issues)
    if issues and judgement["verdict"] == "send":
        judgement.update(verdict="review",headline="资料待核验")
    return {"id":shipment_id,"title":bundle.get("title", ""),"documents":originals,
            "structured":structured,"evidence":evidence,"judgement":judgement,
            "explanation":_explain(judgement)["text"],
            "trace":[{"stage":"ingest","source":"local_text_bundle","documents":list(originals)},
                     {"stage":"extract","fields":len(evidence),"source_lines_preserved":True},
                     {"stage":"validate","issues":len(issues)},
                     {"stage":"decide","verdict":judgement["verdict"]}]}
