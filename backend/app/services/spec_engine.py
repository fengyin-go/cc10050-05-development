"""规格归一判定引擎（纯逻辑）。

这里不依赖 HTTP 与内存仓库，只负责：
1. 按某一版规则判定一条报价样品实际命中的规格口径；
2. 对照基线采用的目标口径判断是否可比（商品 / 包装 / 数量 / 单瓶容量）；
3. 产出可追溯的逐项检查结果：哪条规则的哪个版本、用了哪些输入、哪一项不符。

关键原则：总容量相同不等于规格可比——单件 500ml 与 2 瓶 ×250ml 组合装
总容量都是 500ml，但包装形式与数量不同，不能进同一个单瓶基线。
"""
from __future__ import annotations

import re
from typing import Any

PACK_SINGLE = "单件"
PACK_COMBO = "组合装"
PACK_ANY = "不限"

# 组合装 / 多瓶装的文本线索
_COMBO_MARKERS = ("组合装", "多瓶装", "整箱", "套装", "两瓶", "2瓶", "二瓶", "*2", "×2", "x2", "X2")
_SINGLE_MARKERS = ("单瓶", "单件", "瓶装", "1瓶", "一瓶")


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        m = re.search(r"\d+(?:\.\d+)?", str(value))
        return float(m.group(0)) if m else None


def parse_spec_text(text: str) -> dict[str, Any]:
    """从中文规格文本里粗略解析包装、数量、单瓶容量与总容量。

    例：
      "单瓶500ml"            -> 单件 / 1 / 500 / 500
      "500ml 手工改标仍单瓶"  -> 单件（线索）/ 1 / 500 / 500
      "两瓶各250ml"          -> 组合装 / 2 / 250 / 500
      "250ml*2瓶 组合装"      -> 组合装 / 2 / 250 / 500
    """
    raw = str(text or "")
    lower = raw.lower()
    volumes = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*ml", lower)]
    qty: int | None = None

    # “2×250ml / 2x250ml”：乘号前是件数，后面是单瓶容量
    cross_prefix = re.search(r"(\d+)\s*[×x*]\s*(\d+(?:\.\d+)?)\s*ml", lower)
    # “250ml*2 瓶”：容量在前、件数在后
    cross_suffix = re.search(r"(\d+(?:\.\d+)?)\s*ml\s*[×x*]\s*(\d+)", lower)
    if cross_prefix:
        qty = int(cross_prefix.group(1))
    elif cross_suffix:
        qty = int(cross_suffix.group(2))
    else:
        m = re.search(r"(\d+)\s*瓶", raw)
        if m:
            qty = int(m.group(1))
        m2 = re.search(r"[*×xX]\s*(\d+)", raw)
        if qty is None and m2:
            qty = int(m2.group(1))
        if ("两瓶" in raw or "二瓶" in raw) and qty is None:
            qty = 2

    is_combo = any(marker in raw for marker in _COMBO_MARKERS) or (qty or 1) >= 2
    pack = PACK_COMBO if is_combo else PACK_SINGLE

    unit_ml: float | None = None
    total_ml: float | None = None
    if volumes:
        if qty and qty >= 2 and len(volumes) >= 1:
            # “两瓶各250ml”：出现的容量是单瓶容量
            unit_ml = volumes[0]
            total_ml = unit_ml * qty
        elif len(volumes) >= 2:
            unit_ml, total_ml = volumes[0], volumes[-1]
        else:
            total_ml = volumes[0]
            unit_ml = total_ml / qty if qty and qty >= 2 else total_ml
    if qty is None:
        qty = 1 if pack == PACK_SINGLE else None
    return {
        "包装形式": pack,
        "数量": qty,
        "单瓶容量ml": unit_ml,
        "总容量ml": total_ml,
    }


def quote_fingerprint(quote: dict[str, Any]) -> dict[str, Any]:
    """把试判输入原样留存，保证不可比结论能回溯到具体输入。"""
    keys = [
        "quote_id", "报价编号", "商品标识", "商品名称", "源规格文本",
        "包装形式", "数量", "单瓶容量ml", "总容量ml", "标签状态",
        "报价金额", "站点名称", "报价时间", "备注",
    ]
    return {key: quote.get(key) for key in keys if key in quote}


def normalize_quote(quote: dict[str, Any]) -> dict[str, Any]:
    """补全报价样品的结构化字段：缺省时从源规格文本解析。"""
    result = dict(quote)
    parsed = parse_spec_text(str(quote.get("源规格文本", "")))
    for key, value in parsed.items():
        if result.get(key) in (None, "") and value is not None:
            result[key] = value
    # 总容量兜底：数量 × 单瓶容量
    qty = _to_float(result.get("数量"))
    unit = _to_float(result.get("单瓶容量ml"))
    total = _to_float(result.get("总容量ml"))
    if total is None and qty and unit:
        total = qty * unit
        result["总容量ml"] = total
    if result.get("包装形式") in (None, ""):
        result["包装形式"] = PACK_COMBO if (qty or 1) >= 2 else PACK_SINGLE
    if result.get("数量") in (None, ""):
        result["数量"] = 1
    return result


def _check(dimension: str, expected: Any, actual: Any, passed: bool,
           reason: str = "") -> dict[str, Any]:
    return {
        "维度": dimension,
        "要求": expected,
        "实际": actual,
        "通过": bool(passed),
        "原因": reason or ("" if passed else f"{dimension}不一致"),
    }


def evaluate_rule_version(rule: dict[str, Any], version: dict[str, Any],
                          quote_in: dict[str, Any]) -> dict[str, Any]:
    """用指定版本的规则判定一条报价，返回逐项检查与是否命中。"""
    quote = normalize_quote(quote_in)
    checks: list[dict[str, Any]] = []

    rule_product = str(rule.get("商品标识", "") or "")
    quote_product = str(quote.get("商品标识", "") or "")
    if rule_product:
        passed = rule_product == quote_product
        checks.append(_check(
            "商品", rule_product, quote_product or "（未填写）", passed,
            "" if passed else f"商品对不上：规则适用于 {rule_product}，样品是 {quote_product or '空'}",
        ))

    pack_req = str(version.get("包装要求", PACK_ANY) or PACK_ANY)
    if pack_req and pack_req != PACK_ANY:
        actual_pack = str(quote.get("包装形式", "") or "")
        passed = actual_pack == pack_req
        checks.append(_check(
            "包装", pack_req, actual_pack or "（未识别）", passed,
            "" if passed else f"包装对不上：规则要求{pack_req}，样品为{actual_pack or '未知包装'}",
        ))

    qty_req = _to_float(version.get("数量要求"))
    if qty_req is not None:
        actual_qty = _to_float(quote.get("数量"))
        passed = actual_qty is not None and abs(actual_qty - qty_req) < 1e-9
        checks.append(_check(
            "数量", int(qty_req), quote.get("数量", "（未识别）"), passed,
            "" if passed else f"数量对不上：规则要求 {int(qty_req)} 件/瓶，样品为 {quote.get('数量', '未知')}",
        ))

    unit_req = _to_float(version.get("单瓶容量ml"))
    if unit_req is not None:
        actual_unit = _to_float(quote.get("单瓶容量ml"))
        passed = actual_unit is not None and abs(actual_unit - unit_req) < 1e-6
        checks.append(_check(
            "单瓶容量", f"{unit_req:g}ml",
            f"{actual_unit:g}ml" if actual_unit is not None else "（未识别）",
            passed,
            "" if passed else "单瓶容量对不上",
        ))

    total_req = _to_float(version.get("总容量ml"))
    if total_req is not None:
        actual_total = _to_float(quote.get("总容量ml"))
        passed = actual_total is not None and abs(actual_total - total_req) < 1e-6
        checks.append(_check(
            "总容量", f"{total_req:g}ml",
            f"{actual_total:g}ml" if actual_total is not None else "（未识别）",
            passed,
            "" if passed else "总容量对不上（注意：总容量相同不代表包装/数量可比）",
        ))

    text = str(quote.get("源规格文本", "") or "")
    for keyword in version.get("包含关键词", []) or []:
        keyword = str(keyword).strip()
        if not keyword:
            continue
        passed = keyword.lower() in text.lower()
        checks.append(_check(
            "源文本包含", keyword, text or "（空）", passed,
            "" if passed else f"源规格文本缺少规则要求的关键词「{keyword}」",
        ))
    for keyword in version.get("排除关键词", []) or []:
        keyword = str(keyword).strip()
        if not keyword:
            continue
        hit = keyword.lower() in text.lower()
        checks.append(_check(
            "源文本排除", f"不得包含「{keyword}」", text or "（空）", not hit,
            "" if not hit else f"该版本规则排除含「{keyword}」的样品（规则版本口径）",
        ))

    label_req = str(version.get("标签要求", PACK_ANY) or PACK_ANY)
    if label_req and label_req != PACK_ANY:
        actual_label = str(quote.get("标签状态", "") or "")
        passed = actual_label == label_req
        checks.append(_check(
            "标签状态", label_req, actual_label or "（未填写）", passed,
            "" if passed else f"标签状态对不上：该版规则要求{label_req}，样品为{actual_label or '未知'}",
        ))

    matched = all(item["通过"] for item in checks)
    failed = [item for item in checks if not item["通过"]]
    return {
        "rule_id": rule.get("id"),
        "rule_code": rule.get("rule_code"),
        "规则名称": rule.get("规则名称", ""),
        "rule_version": version.get("version", ""),
        "归一规格": version.get("归一规格", rule.get("归一规格", "")),
        "target_caliber": version.get("target_caliber", rule.get("target_caliber", "")),
        "命中": matched,
        "checks": checks,
        "failed_checks": failed,
        "priority": int(_to_float(rule.get("映射优先级")) or 100),
    }


def classify_quote(rules: list[dict[str, Any]], quote: dict[str, Any],
                   versions: dict[int, str] | None = None) -> dict[str, Any]:
    """用给定规则集合（指定版本）判定一条报价，选出实际命中的规则。"""
    normalized = normalize_quote(quote)
    evaluations: list[dict[str, Any]] = []
    for rule in rules:
        version = pick_version(rule, (versions or {}).get(int(rule.get("id", -1))))
        if version is None:
            continue
        evaluations.append(evaluate_rule_version(rule, version, normalized))

    hits = [item for item in evaluations if item["命中"]]
    # 优先级数字小的优先；同优先级时检查项更多（更具体）的优先
    hits.sort(key=lambda item: (item["priority"], -len(item["checks"])))
    chosen = hits[0] if hits else None

    if chosen:
        actual_spec = chosen["归一规格"]
        actual_caliber = chosen["target_caliber"]
        matched_ref = f'{chosen["rule_code"]}@{chosen["rule_version"]}'
    else:
        parsed = parse_spec_text(str(normalized.get("源规格文本", "")))
        actual_spec = "未命中任何所选规则"
        actual_caliber = ""
        matched_ref = ""

    return {
        "input": quote_fingerprint(normalized),
        "normalized": {
            "商品标识": normalized.get("商品标识", ""),
            "包装形式": normalized.get("包装形式", ""),
            "数量": normalized.get("数量", ""),
            "单瓶容量ml": normalized.get("单瓶容量ml", ""),
            "总容量ml": normalized.get("总容量ml", ""),
        },
        "matched_rule": chosen,
        "matched_rule_ref": matched_ref,
        "actual_spec": actual_spec,
        "actual_caliber": actual_caliber,
        "evaluations": evaluations,
    }


def pick_version(rule: dict[str, Any], version: str | None = None) -> dict[str, Any] | None:
    versions = rule.get("versions") or []
    if not versions:
        # 兼容直接把当前版本字段平铺在行上的规则
        return {
            "version": rule.get("active_version", "v1"),
            "归一规格": rule.get("归一规格", ""),
            "target_caliber": rule.get("target_caliber", ""),
            "包装要求": rule.get("包装要求", PACK_ANY),
            "数量要求": rule.get("数量要求"),
            "单瓶容量ml": rule.get("单瓶容量ml"),
            "总容量ml": rule.get("总容量ml"),
            "包含关键词": rule.get("包含关键词", []),
            "排除关键词": rule.get("排除关键词", []),
            "标签要求": rule.get("标签要求", PACK_ANY),
        }
    wanted = version or rule.get("active_version") or versions[-1].get("version")
    for item in versions:
        if item.get("version") == wanted:
            return item
    return versions[-1]


def comparability_against(caliber: dict[str, Any] | None,
                          classification: dict[str, Any]) -> dict[str, Any]:
    """把分类结果与基线采用的目标口径对比，给出是否参与计价及不符项。"""
    if not caliber:
        return {"可比": True, "mismatches": [], "reason": ""}

    normalized = classification.get("normalized", {})
    mismatches: list[dict[str, Any]] = []

    product_req = str(caliber.get("商品标识", "") or "")
    if product_req:
        actual = str(normalized.get("商品标识", "") or "")
        if actual != product_req:
            mismatches.append(_check("商品", product_req, actual or "（未填写）", False))

    pack_req = str(caliber.get("包装形式", "") or "")
    if pack_req:
        actual = str(normalized.get("包装形式", "") or "")
        if actual != pack_req:
            mismatches.append(_check(
                "包装", pack_req, actual or "（未识别）", False,
                f"基线口径是{pack_req}，实际分类为{actual or '未知包装'}；总容量相同也不可比",
            ))

    qty_req = _to_float(caliber.get("数量"))
    if qty_req is not None:
        actual_qty = _to_float(normalized.get("数量"))
        if actual_qty is None or abs(actual_qty - qty_req) >= 1e-9:
            mismatches.append(_check(
                "数量", int(qty_req), normalized.get("数量", "（未识别）"), False,
                f"基线口径要求 {int(qty_req)} 件/瓶，实际数量不符",
            ))

    unit_req = _to_float(caliber.get("单瓶容量ml"))
    if unit_req is not None:
        actual_unit = _to_float(normalized.get("单瓶容量ml"))
        if actual_unit is None or abs(actual_unit - unit_req) >= 1e-6:
            mismatches.append(_check(
                "单瓶容量", f"{unit_req:g}ml",
                f"{actual_unit:g}ml" if actual_unit is not None else "（未识别）", False,
            ))

    comparable = not mismatches and classification.get("matched_rule") is not None
    reasons = [item["原因"] for item in mismatches if item.get("原因")]
    if not comparable and not reasons:
        reasons.append("样品未命中所选规则，无法确认实际规格口径")
    return {
        "可比": comparable,
        "mismatches": mismatches,
        "reason": "；".join(reasons),
    }


def mean_price(quotes: list[dict[str, Any]]) -> float | None:
    prices = [_to_float(q.get("报价金额")) for q in quotes]
    prices = [p for p in prices if p is not None]
    if not prices:
        return None
    return round(sum(prices) / len(prices) + 1e-9, 2)
