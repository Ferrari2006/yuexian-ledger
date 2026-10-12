"""单证文本进入抽取之前的预处理。

噪声行先丢掉。滤完后如果栏位一条都不剩，回退到只做换行归一的原文，
避免过滤误伤把整票洗空。原文本身就没有栏位时，标记缺失，不抛错。
"""

from __future__ import annotations

import re

_NOISE = re.compile(
    r"^(?:"
    r"第\s*\d+\s*页(?:\s*/\s*共\s*\d+\s*页)?"
    r"|page\s*\d+(?:\s*/\s*\d+)?"
    r"|[-—_=*·.]{3,}"
    r"|.*(?:水印|仅供参考|草稿勿用).*"
    r"|[\ufffd?]{2,}"
    r")$",
    re.IGNORECASE,
)
_FIELD = re.compile(r"^(扫描)?([^：:]+)[：:]\s*(.+)$")


def preprocess_text(text: str) -> dict:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    kept: list[str] = []
    dropped = 0
    for raw in normalized.split("\n"):
        line = raw.strip()
        if _is_noise(line):
            dropped += 1
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    if not _has_field(cleaned) and _has_field(normalized):
        return {
            "text": normalized.strip(),
            "dropped_noise": dropped,
            "fallback": "noise_filter",
            "missing": [],
        }
    if not cleaned or not _has_field(cleaned):
        return {
            "text": cleaned,
            "dropped_noise": dropped,
            "fallback": "missing",
            "missing": ["document"],
        }
    return {
        "text": cleaned,
        "dropped_noise": dropped,
        "fallback": "none",
        "missing": [],
    }


def _is_noise(line: str) -> bool:
    if not line:
        return True
    return _NOISE.fullmatch(line) is not None


def _has_field(text: str) -> bool:
    return any(_FIELD.match(line.strip()) for line in text.splitlines())
