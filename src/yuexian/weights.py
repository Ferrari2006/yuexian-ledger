"""公斤字段的保守数值解析，不推测未知单位或错误分隔符。"""

from __future__ import annotations

import math
import re

_KG_SUFFIX = re.compile(r"\s*(?:kg|kgs|kilograms?|公斤|千克)\s*$", re.IGNORECASE)
_NUMBER = re.compile(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?")


def parse_weight(value) -> int | float | None:
    """返回有限数值；非法内容返回 None，零和负数交给完整性检查处理。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return value if math.isfinite(value) else None
        except OverflowError:
            return None
    if not isinstance(value, str):
        return None
    text = _KG_SUFFIX.sub("", value.strip().replace("，", ",")).strip()
    if not _NUMBER.fullmatch(text):
        return None
    text = text.replace(",", "")
    try:
        number = float(text) if "." in text else int(text)
        return number if math.isfinite(number) else None
    except (ValueError, OverflowError):
        return None
