"""从单证文本抽出字段。

离线抽取用栏位标签，保证没有密钥时测试和演示仍可复算。
设置环境变量 DASHSCOPE_API_KEY 后，可用千问再抽一遍；规则阶段不读模型的结论。
"""

from __future__ import annotations

import os
import re

from yuexian.weights import parse_weight

FIELD_LINE = re.compile(r"^(扫描)?([^：:]+)[：:]\s*(.+)$")

WEIGHT_KEYS = {
    "GROSS_WEIGHT_KG": "gross_weight_kg",
    "毛重（公斤）": "gross_weight_kg",
    "扫描毛重（公斤）": "gross_weight_kg",
}
ID_KEYS = {
    "CONTAINER_NO": "container_no",
    "SEAL_NO": "seal_no",
    "柜号": "container_no",
    "封条号": "seal_no",
}
STATION_KEYS = {"DOC_STATION", "单证站点"}
SHIPMENT_KEYS = {"SHIPMENT", "票号"}
COUNTRY_KEYS = {
    "COUNTRY": "collapsed",
    "国家": "collapsed",
    "TRADE_COUNTRY": "trade",
    "贸易国": "trade",
    "DEPARTURE_COUNTRY": "departure",
    "启运国": "departure",
    "ORIGIN_COUNTRY": "origin",
    "原产国": "origin",
    "DESTINATION_COUNTRY": "destination",
    "最终目的国": "destination",
}


def extract_document(text: str) -> dict:
    station = "unknown"
    shipment_id = ""
    observations: dict[str, list[dict]] = {
        "gross_weight_kg": [],
        "container_no": [],
        "seal_no": [],
    }
    countries: dict[str, str] = {}
    collapsed = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        matched = FIELD_LINE.match(line)
        if not matched:
            continue
        noisy, key, value = matched.group(1), matched.group(2).strip(), matched.group(3).strip()
        label = "ocr_error" if noisy or key.startswith("扫描") else "rewrite"
        if key in STATION_KEYS:
            station = value
            continue
        if key in SHIPMENT_KEYS:
            shipment_id = value
            continue
        if key in WEIGHT_KEYS:
            observations["gross_weight_kg"].append(
                {"station": station, "value": _number(value), "label": label}
            )
        elif key in ID_KEYS:
            observations[ID_KEYS[key]].append(
                {"station": station, "value": value, "label": label}
            )
        elif key in COUNTRY_KEYS:
            slot = COUNTRY_KEYS[key]
            if slot == "collapsed":
                collapsed = value
            else:
                countries[slot] = value
    if collapsed:
        countries["collapsed_value"] = collapsed
    return {
        "shipment_id": shipment_id,
        "station": station,
        "observations": observations,
        "countries": countries,
    }


def extract_with_qwen(text: str) -> dict | None:
    """有密钥时请求千问 JSON；未配置返回 None，失败返回错误标记。"""
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import json
        import urllib.request

        body = json.dumps(
            {
                "model": os.environ.get("QWEN_MODEL", "qwen-plus"),
                "messages": [
                    {
                        "role": "system",
                        "content": "只输出 JSON。字段为 gross_weight_kg, container_no, seal_no, country。不要判断能不能申报。",
                    },
                    {"role": "user", "content": text},
                ],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        return {"raw": content, "source": "qwen"}
    except Exception as exc:  # 网络或密钥问题不阻断规则演示
        return {"error": str(exc), "source": "qwen"}


def _number(value: str):
    number = parse_weight(value)
    # 保留无法解析的原文，规则层据此要求核验，而不是默默丢弃。
    return value if number is None else number
