"""试判 → 重算申请 → 确认 → 发布 的工作流服务。

核心不变量：
* 规则更正只追加新版本，旧版本不可变；
* 重算申请在生成时冻结“该轮采用的口径 + 分类结果 + 排除报价”，
  确认时再把基线金额与参与报价写进同一个 confirmation 快照；
* 之后任何规则更正、筛选变化都不会改写旧申请，详情只按 id 读快照；
* 发布只搬运确认快照里的价格与样本依据，绝不重新计算。
"""
from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any

from app.services.spec_engine import (
    PACK_ANY,
    PACK_COMBO,
    PACK_SINGLE,
    classify_quote,
    comparability_against,
    mean_price,
    normalize_quote,
    parse_spec_text,
    pick_version,
)
from app.store import store

PRODUCT_ID = "SP-W500"
CALIBER_SINGLE_500 = "SINGLE_500"
CALIBER_COMBO_2X250 = "COMBO_2X250"


class WorkflowDB:
    """工作流自有内存表：不进通用 store，避免改变 /api/health 的模块集合。"""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}

    def rows(self, name: str) -> list[dict[str, Any]]:
        return self.tables.setdefault(name, [])

    def find(self, name: str, row_id: int) -> dict[str, Any] | None:
        for row in self.rows(name):
            if int(row.get("id", 0)) == row_id:
                return row
        return None


db = WorkflowDB()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deep(value: Any) -> Any:
    return copy.deepcopy(value)


class WorkflowService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._seeded = False

    # ---------------- 种子场景 ----------------

    def ensure_seed(self) -> None:
        with self._lock:
            if self._seeded:
                return
            rules = db.rows("spec_rule")
            if not rules:
                rules.extend(self._seed_rules())
            quotes = db.rows("price_quote")
            if not quotes:
                quotes.extend(self._seed_quotes())
            baselines = db.rows("spec_baseline")
            if not baselines:
                baselines.extend(self._seed_baselines())
            db.rows("trial_record")
            db.rows("recalc_round")
            # 基础表已就绪；先打标记，避免后续调用 run_trial 时递归播种
            self._seeded = True
            # 同步一条场景基线到通用价格基线库表，保留通用动作入口
            for baseline in db.rows("spec_baseline"):
                self._upsert_generic_baseline(baseline)

    def _seed_rules(self) -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "rule_code": "R-SINGLE-500",
                "规则名称": "单瓶500ml重叠规则",
                "商品标识": PRODUCT_ID,
                "商品名称": "500ml饮用矿泉水（同商品）",
                "归一规格": "单瓶500ml",
                "target_caliber": CALIBER_SINGLE_500,
                "映射优先级": 1,
                "active_version": "v1",
                "status": "已启用",
                "重叠组": "总量500ml",
                "versions": [
                    {
                        "version": "v1",
                        "归一规格": "单瓶500ml",
                        "target_caliber": CALIBER_SINGLE_500,
                        "包装要求": PACK_SINGLE,
                        "数量要求": 1,
                        "单瓶容量ml": 500,
                        "总容量ml": 500,
                        "包含关键词": ["500ml"],
                        # 旧版口径把“手工改标”视为标识异常，排除该单瓶报价——
                        # 这正是新旧判定冲突的来源。
                        "排除关键词": ["手工改标", "改标"],
                        "标签要求": "原厂标签",
                        "版本说明": "旧版：手工改标/非原厂标签样品不纳入单瓶基线",
                        "created_at": "2026-11-18T09:00:00+00:00",
                        "created_by": "规则组",
                    }
                ],
            },
            {
                "id": 2,
                "rule_code": "R-COMBO-2X250",
                "规则名称": "两瓶250ml组合装重叠规则",
                "商品标识": PRODUCT_ID,
                "商品名称": "500ml饮用矿泉水（同商品）",
                "归一规格": "组合装2×250ml",
                "target_caliber": CALIBER_COMBO_2X250,
                "映射优先级": 2,
                "active_version": "v1",
                "status": "已启用",
                "重叠组": "总量500ml",
                "versions": [
                    {
                        "version": "v1",
                        "归一规格": "组合装2×250ml",
                        "target_caliber": CALIBER_COMBO_2X250,
                        "包装要求": PACK_COMBO,
                        "数量要求": 2,
                        "单瓶容量ml": 250,
                        "总容量ml": 500,
                        "包含关键词": ["250ml"],
                        "排除关键词": [],
                        "标签要求": "不限",
                        "版本说明": "按包装与数量区分：两瓶各250ml是组合装，不是单瓶500ml",
                        "created_at": "2026-11-18T09:05:00+00:00",
                        "created_by": "规则组",
                    }
                ],
            },
        ]

    def _seed_quotes(self) -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "报价编号": "Q-100",
                "商品标识": PRODUCT_ID,
                "商品名称": "500ml饮用矿泉水（同商品）",
                "源规格文本": "单瓶500ml 原厂原标",
                "包装形式": PACK_SINGLE,
                "数量": 1,
                "单瓶容量ml": 500,
                "总容量ml": 500,
                "标签状态": "原厂标签",
                "报价金额": 100,
                "站点名称": "官方旗舰店",
                "status": "已解析",
            },
            {
                "id": 2,
                "报价编号": "Q-90",
                "商品标识": PRODUCT_ID,
                "商品名称": "500ml饮用矿泉水（同商品）",
                "源规格文本": "500ml 手工改标（实物仍为单瓶500ml）",
                "包装形式": PACK_SINGLE,
                "数量": 1,
                "单瓶容量ml": 500,
                "总容量ml": 500,
                "标签状态": "手工改标",
                "报价金额": 90,
                "站点名称": "折扣专营店",
                "status": "已解析",
                "备注": "手工改标，包装容量未变，仍为单瓶",
            },
            {
                "id": 3,
                "报价编号": "Q-60",
                "商品标识": PRODUCT_ID,
                "商品名称": "500ml饮用矿泉水（同商品）",
                "源规格文本": "两瓶各250ml，250ml*2组合装，总量500ml",
                "包装形式": PACK_COMBO,
                "数量": 2,
                "单瓶容量ml": 250,
                "总容量ml": 500,
                "标签状态": "原厂标签",
                "报价金额": 60,
                "站点名称": "量贩超市",
                "status": "已解析",
            },
        ]

    def _single_caliber(self) -> dict[str, Any]:
        return {
            "caliber_code": CALIBER_SINGLE_500,
            "规格口径": "单瓶500ml",
            "商品标识": PRODUCT_ID,
            "包装形式": PACK_SINGLE,
            "数量": 1,
            "单瓶容量ml": 500,
        }

    def _seed_baselines(self) -> list[dict[str, Any]]:
        caliber = self._single_caliber()
        return [
            {
                "id": 1,
                "baseline_code": "BL-SP-W500-S500",
                "商品标识": PRODUCT_ID,
                "商品名称": "500ml饮用矿泉水（同商品）",
                "归一规格": "单瓶500ml",
                "caliber": caliber,
                "基线价格": 100.0,
                "采样窗口": "7d",
                "status": "已生效",
                "updated_at": "2026-11-20T10:00:00+00:00",
                "current_confirmation": {
                    "confirmed_at": "2026-11-20T10:00:00+00:00",
                    "confirmed_by": "数据工程组",
                    "baseline_price": 100.0,
                    "currency": "CNY",
                    "quote_count": 1,
                    "participating": [
                        {
                            "quote_id": 1,
                            "报价编号": "Q-100",
                            "报价金额": 100,
                            "matched_rule_ref": "R-SINGLE-500@v1",
                            "actual_spec": "单瓶500ml",
                        }
                    ],
                    "excluded": [
                        {
                            "quote_id": 2,
                            "报价编号": "Q-90",
                            "报价金额": 90,
                            "reason": "R-SINGLE-500@v1 排除含「手工改标」的样品，且要求原厂标签",
                            "matched_rule_ref": "",
                        },
                        {
                            "quote_id": 3,
                            "报价编号": "Q-60",
                            "报价金额": 60,
                            "reason": "基线口径是单件，实际为组合装；数量要求1，实际2；总容量相同也不可比",
                            "matched_rule_ref": "R-COMBO-2X250@v1",
                        },
                    ],
                    "excluded_amount": 150.0,
                    "rule_batch": [
                        {"rule_id": 1, "rule_code": "R-SINGLE-500", "version": "v1"},
                        {"rule_id": 2, "rule_code": "R-COMBO-2X250", "version": "v1"},
                    ],
                    "caliber_text": "SP-W500 / 单瓶500ml（单件 × 1瓶 × 500ml）",
                },
                "publication": {
                    "published_at": "2026-11-20T10:05:00+00:00",
                    "baseline_price": 100.0,
                    "sample_basis_quote_ids": [1],
                    "rule_batch_refs": ["R-SINGLE-500@v1", "R-COMBO-2X250@v1"],
                    "consistent": True,
                },
            }
        ]

    # ---------------- 查询 ----------------

    def list_rules(self, product: str | None = None) -> list[dict[str, Any]]:
        self.ensure_seed()
        rules = db.rows("spec_rule")
        if product:
            rules = [r for r in rules if str(r.get("商品标识", "")) == product]
        return [_deep(r) for r in rules]

    def get_rule(self, rule_id: int) -> dict[str, Any] | None:
        self.ensure_seed()
        row = db.find("spec_rule", rule_id)
        return _deep(row) if row else None

    def list_quotes(self, product: str | None = None) -> list[dict[str, Any]]:
        self.ensure_seed()
        quotes = db.rows("price_quote")
        if product:
            quotes = [q for q in quotes if str(q.get("商品标识", "")) == product]
        return [_deep(q) for q in quotes]

    def list_baselines(self) -> list[dict[str, Any]]:
        self.ensure_seed()
        return [_deep(r) for r in db.rows("spec_baseline")]

    def get_baseline(self, baseline_id: int) -> dict[str, Any] | None:
        self.ensure_seed()
        row = db.find("spec_baseline", baseline_id)
        return _deep(row) if row else None

    # ---------------- 报价登记 ----------------

    def create_rich_rule_from_entry(self, entry: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        """把通用登记表单创建的规则派生为带结构化条件与版本的可试判规则。"""
        self.ensure_seed()
        with self._lock:
            rows = db.rows("spec_rule")
            rid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            spec_text = f'{values.get("归一规格", "")} {values.get("源规格文本", "")}'
            parsed = parse_spec_text(spec_text)
            ml_token = ""
            import re
            match = re.search(r"(\d+(?:\.\d+)?)\s*ml", spec_text.lower())
            if match:
                ml_token = f"{match.group(1)}ml"
            include_keywords = [ml_token] if ml_token else []
            qty = parsed.get("数量") or 1
            unit_ml = parsed.get("单瓶容量ml")
            total_ml = parsed.get("总容量ml")
            rule = {
                "id": rid,
                "rule_code": f"R-CUSTOM-{rid}",
                "规则名称": entry.get("规则名称", f"自定义规则{rid}"),
                "商品标识": str(values.get("商品标识", "") or ""),
                "商品名称": "",
                "归一规格": entry.get("归一规格", ""),
                "target_caliber": f"CUSTOM_{rid}",
                "映射优先级": entry.get("映射优先级", "100"),
                "active_version": "v1",
                "status": "已启用" if entry.get("status") != "草稿" else "草稿",
                "normalizer_id": entry.get("id"),
                "重叠组": ml_token and f"总量{total_ml:g}ml" if total_ml else "",
                "versions": [{
                    "version": "v1",
                    "归一规格": entry.get("归一规格", ""),
                    "target_caliber": f"CUSTOM_{rid}",
                    "包装要求": parsed.get("包装形式", PACK_ANY),
                    "数量要求": qty,
                    "单瓶容量ml": unit_ml or "",
                    "总容量ml": total_ml or "",
                    "包含关键词": include_keywords,
                    "排除关键词": [],
                    "标签要求": "不限",
                    "版本说明": "由通用规格归一规则登记派生",
                    "created_at": _now(),
                    "created_by": "运营登记",
                }],
            }
            rows.append(rule)
            return _deep(rule)

    def create_quote(self, values: dict[str, Any]) -> dict[str, Any]:
        self.ensure_seed()
        with self._lock:
            rows = db.rows("price_quote")
            qid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            quote = {
                "id": qid,
                "报价编号": values.get("报价编号") or f"Q-{qid}",
                "商品标识": str(values.get("商品标识", "") or PRODUCT_ID),
                "商品名称": values.get("商品名称", ""),
                "源规格文本": str(values.get("源规格文本", "") or ""),
                "包装形式": values.get("包装形式", "") or "",
                "数量": values.get("数量", "") or "",
                "单瓶容量ml": values.get("单瓶容量ml", "") or "",
                "总容量ml": values.get("总容量ml", "") or "",
                "标签状态": values.get("标签状态", "") or "",
                "报价金额": values.get("报价金额", ""),
                "站点名称": values.get("站点名称", ""),
                "status": "已解析",
            }
            quote = normalize_quote(quote)
            rows.append(quote)
            return _deep(quote)

    # ---------------- 规则更正（追加版本） ----------------

    def correct_rule(self, rule_id: int, changes: dict[str, Any],
                     operator: str = "数据工程组") -> tuple[dict[str, Any] | None, str]:
        self.ensure_seed()
        with self._lock:
            rule = db.find("spec_rule", rule_id)
            if rule is None:
                return None, f"规格规则 {rule_id} 不存在"
            versions = rule.setdefault("versions", [])
            old = pick_version(rule) or {}
            try:
                next_no = max(int(str(v.get("version", "v0")).lstrip("v")) for v in versions) + 1
            except ValueError:
                next_no = len(versions) + 1
            new_version = f"v{next_no}"

            def _list(value: Any) -> list[str]:
                if isinstance(value, list):
                    return [str(v).strip() for v in value if str(v).strip()]
                if value is None:
                    return []
                return [part.strip() for part in str(value).replace("，", ",").split(",") if part.strip()]

            key_map = {
                "归一规格": "归一规格",
                "包装要求": "包装要求",
                "数量要求": "数量要求",
                "单瓶容量ml": "单瓶容量ml",
                "总容量ml": "总容量ml",
                "标签要求": "标签要求",
                "版本说明": "版本说明",
            }
            version_row: dict[str, Any] = _deep(old)
            version_row["version"] = new_version
            for payload_key, field in key_map.items():
                if payload_key in changes and changes[payload_key] != "":
                    version_row[field] = changes[payload_key]
            for list_field in ("包含关键词", "排除关键词"):
                if list_field in changes:
                    version_row[list_field] = _list(changes[list_field])
            # 数值化
            for num_field in ("数量要求", "单瓶容量ml", "总容量ml"):
                if version_row.get(num_field) not in (None, ""):
                    try:
                        version_row[num_field] = float(version_row[num_field])
                        if num_field == "数量要求":
                            version_row[num_field] = int(version_row[num_field])
                    except (TypeError, ValueError):
                        pass
            if changes.get("correction_note"):
                version_row["版本说明"] = changes["correction_note"]
            version_row["created_at"] = _now()
            version_row["created_by"] = operator
            version_row["correction"] = True
            versions.append(version_row)
            rule["active_version"] = new_version
            if changes.get("规则名称"):
                rule["规则名称"] = changes["规则名称"]
            if changes.get("归一规格"):
                rule["归一规格"] = changes["归一规格"]
            if changes.get("status"):
                rule["status"] = changes["status"]
            rule["last_corrected_at"] = _now()
            rule["last_corrected_by"] = operator
            return _deep(rule), f"规则已更正：{rule.get('rule_code')} 新版本 {new_version} 已启用，旧版本保留可追溯"

    # ---------------- 试判 ----------------

    def run_trial(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_seed()
        rule_ids = [int(x) for x in payload.get("rule_ids", []) if str(x).strip() != ""]
        version_pins = {
            int(k): str(v) for k, v in (payload.get("rule_versions") or {}).items()
        }
        rules = [db.find("spec_rule", rid) for rid in rule_ids]
        rules = [r for r in rules if r is not None]

        # 样品来源：内联 samples 优先，其次 quote_ids，最后 product 下全部报价
        samples: list[dict[str, Any]] = []
        if payload.get("samples"):
            for item in payload["samples"]:
                if str(item.get("quote_id", "")).strip() or item.get("报价金额") != "":
                    samples.append(dict(item))
        if payload.get("quote_ids"):
            for qid in payload["quote_ids"]:
                row = db.find("price_quote", int(qid))
                if row:
                    samples.append(_deep(row))
        if not samples and payload.get("use_product_quotes"):
            product = payload.get("product") or PRODUCT_ID
            samples = [_deep(q) for q in self.list_quotes(str(product))]

        baseline_id = payload.get("baseline_id")
        baseline = db.find("spec_baseline", int(baseline_id)) if baseline_id else None
        caliber = (baseline or {}).get("caliber") or payload.get("caliber") or None

        rule_snapshot = [self._rule_ref(r, version_pins.get(int(r["id"]))) for r in rules]
        results = []
        for sample in samples:
            classification = classify_quote(rules, sample, version_pins or None)
            verdict = comparability_against(caliber, classification) if caliber else {
                "可比": classification.get("matched_rule") is not None,
                "mismatches": [],
                "reason": "" if classification.get("matched_rule") else "未命中所选规则",
            }
            price = sample.get("报价金额")
            results.append({
                "key": str(sample.get("quote_id") or sample.get("id") or len(results) + 1),
                "quote_id": sample.get("quote_id", sample.get("id")),
                "报价编号": sample.get("报价编号", ""),
                "报价金额": price,
                "站点名称": sample.get("站点名称", ""),
                **classification,
                "verdict": verdict,
                "comparable": verdict["可比"],
            })

        record = {
            "id": max((int(r.get("id", 0)) for r in db.rows("trial_record")), default=0) + 1,
            "ran_at": _now(),
            "operator": payload.get("operator", "运营试判"),
            "product": payload.get("product") or (rules[0].get("商品标识") if rules else ""),
            "baseline_id": baseline.get("id") if baseline else None,
            "caliber": _deep(caliber),
            "rule_ids": rule_ids,
            "rule_batch": rule_snapshot,
            "sample_count": len(results),
            "results": results,
        }
        with self._lock:
            db.rows("trial_record").append(record)
        return _deep(record)

    def get_trial(self, trial_id: int) -> dict[str, Any] | None:
        self.ensure_seed()
        row = db.find("trial_record", trial_id)
        return _deep(row) if row else None

    def _rule_ref(self, rule: dict[str, Any], version: str | None = None) -> dict[str, Any]:
        v = pick_version(rule, version) or {}
        return {
            "rule_id": rule.get("id"),
            "rule_code": rule.get("rule_code"),
            "规则名称": rule.get("规则名称", ""),
            "version": v.get("version", rule.get("active_version", "v1")),
            "归一规格": v.get("归一规格", rule.get("归一规格", "")),
            "criteria": {
                "包装要求": v.get("包装要求", "不限"),
                "数量要求": v.get("数量要求"),
                "单瓶容量ml": v.get("单瓶容量ml"),
                "总容量ml": v.get("总容量ml"),
                "包含关键词": v.get("包含关键词", []),
                "排除关键词": v.get("排除关键词", []),
                "标签要求": v.get("标签要求", "不限"),
            },
        }

    # ---------------- 重算申请（不可变轮次） ----------------

    def create_round_from_trial(self, trial_id: int,
                                baseline_id: int | None = None) -> tuple[dict[str, Any] | None, str]:
        self.ensure_seed()
        with self._lock:
            trial = db.find("trial_record", trial_id)
            if trial is None:
                return None, f"试判记录 {trial_id} 不存在"
            bid = baseline_id or trial.get("baseline_id") or 1
            baseline = db.find("spec_baseline", int(bid))
            caliber = (baseline or {}).get("caliber") or trial.get("caliber") or self._single_caliber()

            participating, excluded = self._split_results(trial.get("results", []))
            round_id = max((int(r.get("id", 0)) for r in db.rows("recalc_round")), default=0) + 1
            row = {
                "id": round_id,
                "code": f"RC-{round_id:04d}",
                "kind": "重算申请",
                "source": "trial",
                "trial_id": trial_id,
                "baseline_id": baseline.get("id") if baseline else None,
                "baseline_code": (baseline or {}).get("baseline_code", ""),
                "商品标识": caliber.get("商品标识") or trial.get("product") or PRODUCT_ID,
                "商品名称": (baseline or {}).get("商品名称", ""),
                "caliber": _deep(caliber),
                "caliber_text": self._caliber_text(caliber),
                "status": "待确认",
                "created_at": _now(),
                "created_by": "值班员",
                # 生成申请的瞬间冻结：该轮真正采用的规则批次与分类/排除结果
                "adopted": {
                    "adopted_at": _now(),
                    "rule_batch": _deep(trial.get("rule_batch", [])),
                    "caliber": _deep(caliber),
                    "caliber_text": self._caliber_text(caliber),
                    "classifications": _deep(trial.get("results", [])),
                    "participating": participating,
                    "excluded": excluded,
                    "excluded_amount": self._sum_amount(excluded),
                    "preview_price": mean_price(participating),
                },
                "confirmation": None,
                "publication": None,
            }
            db.rows("recalc_round").append(row)
            if baseline is not None:
                baseline["status"] = "待重算"
            return _deep(row), "已生成重算申请，可到价格基线库打开本轮"

    def create_round_for_baseline_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """通用资源动作「重算基线」的挂钩：按当前启用规则生成一轮申请。"""
        self.ensure_seed()
        product = str(entry.get("商品标识", "") or PRODUCT_ID)
        baseline = self._find_or_create_spec_baseline(entry)
        record = self.recompute_preview(baseline["id"], product=product, confirm=False)
        return record

    def _find_or_create_spec_baseline(self, entry: dict[str, Any]) -> dict[str, Any]:
        target_spec = str(entry.get("归一规格", "") or "单瓶500ml")
        for b in db.rows("spec_baseline"):
            if str(b.get("商品标识")) == str(entry.get("商品标识")) and b.get("归一规格") == target_spec:
                return b
        with self._lock:
            rows = db.rows("spec_baseline")
            bid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            caliber = self._caliber_from_spec(target_spec, str(entry.get("商品标识", PRODUCT_ID)))
            row = {
                "id": bid,
                "baseline_code": f"BL-{bid:04d}",
                "商品标识": entry.get("商品标识", PRODUCT_ID),
                "商品名称": entry.get("商品名称", ""),
                "归一规格": target_spec,
                "caliber": caliber,
                "基线价格": float(entry.get("基线价格") or 0) or None,
                "采样窗口": entry.get("采样窗口", "7d") or "7d",
                "status": "待重算",
                "updated_at": _now(),
                "current_confirmation": None,
                "publication": None,
                "generic_entry_id": entry.get("id"),
            }
            rows.append(row)
            return row

    def recompute_preview(self, baseline_id: int, product: str | None = None,
                          confirm: bool = False) -> dict[str, Any]:
        """按当前启用的最新规则 + 报价池重新分类，生成新一轮（不复用旧快照）。"""
        self.ensure_seed()
        baseline = db.find("spec_baseline", baseline_id)
        if baseline is None:
            raise ValueError(f"基线 {baseline_id} 不存在")
        product = product or baseline.get("商品标识") or PRODUCT_ID
        rules = [r for r in self.list_rules(product) if r.get("status") == "已启用"]
        quotes = self.list_quotes(product)
        trial = self.run_trial({
            "rule_ids": [r["id"] for r in rules],
            "samples": quotes,
            "baseline_id": baseline_id,
            "operator": "基线复算",
        })
        round_row, _ = self.create_round_from_trial(trial["id"], baseline_id)
        assert round_row is not None
        round_row["source"] = "recompute-latest"
        with self._lock:
            stored = db.find("recalc_round", round_row["id"])
            if stored is not None:
                stored["source"] = "recompute-latest"
        if confirm:
            round_row, _ = self.confirm_round(round_row["id"])
        return round_row  # type: ignore[return-value]

    def list_rounds(self, baseline_id: int | None = None) -> list[dict[str, Any]]:
        self.ensure_seed()
        rows = db.rows("recalc_round")
        if baseline_id is not None:
            rows = [r for r in rows if r.get("baseline_id") == baseline_id]
        return [_deep(r) for r in sorted(rows, key=lambda r: -int(r.get("id", 0)))]

    def get_round(self, round_id: int) -> dict[str, Any] | None:
        self.ensure_seed()
        row = db.find("recalc_round", round_id)
        return _deep(row) if row else None

    def confirm_round(self, round_id: int,
                      operator: str = "值班员") -> tuple[dict[str, Any] | None, str]:
        """把基线金额与参与报价写进同一份确认快照。旧申请不受新规则影响。"""
        self.ensure_seed()
        with self._lock:
            row = db.find("recalc_round", round_id)
            if row is None:
                return None, f"重算申请 {round_id} 不存在"
            adopted = row.get("adopted") or {}
            participating = _deep(adopted.get("participating", []))
            excluded = _deep(adopted.get("excluded", []))
            price = mean_price(participating)
            if price is None:
                return row, "没有任何可比报价，无法确认基线金额"
            confirmation = {
                "confirmed_at": _now(),
                "confirmed_by": operator,
                "baseline_price": price,
                "currency": "CNY",
                "quote_count": len(participating),
                # 金额与参与报价来自同一次确认：整体冻结
                "participating": participating,
                "excluded": excluded,
                "excluded_amount": self._sum_amount(excluded),
                "participating_amount": self._sum_amount(participating),
                "rule_batch": _deep(adopted.get("rule_batch", [])),
                "caliber": _deep(adopted.get("caliber", {})),
                "caliber_text": adopted.get("caliber_text", ""),
            }
            row["confirmation"] = confirmation
            row["status"] = "已确认"
            row["confirmed_at"] = confirmation["confirmed_at"]
            return _deep(row), f"本轮已确认：基线金额 {price:.2f}，参与报价 {len(participating)} 条，排除金额 {confirmation['excluded_amount']:.2f}"

    def publish_round(self, round_id: int,
                      operator: str = "值班员") -> tuple[dict[str, Any] | None, str]:
        """发布：价格与样本依据必须来自同一份确认快照，不再重算。"""
        self.ensure_seed()
        with self._lock:
            row = db.find("recalc_round", round_id)
            if row is None:
                return None, f"重算申请 {round_id} 不存在"
            conf = row.get("confirmation")
            if not conf:
                # 允许“确认并发布”一步完成：确认信封与发布仍来自同一次原子操作。
                confirmed, message = self.confirm_round(round_id, operator)
                if confirmed is None or not confirmed.get("confirmation"):
                    return confirmed, message
                conf = row.get("confirmation")
            price = conf["baseline_price"]
            quote_ids = [q.get("quote_id") for q in conf.get("participating", [])]
            rule_refs = [
                f'{r.get("rule_code")}@{r.get("version")}'
                for r in conf.get("rule_batch", [])
            ]
            basis_amount = mean_price(conf.get("participating", []))
            consistent = basis_amount is not None and abs(float(basis_amount) - float(price)) < 0.005
            publication = {
                "published_at": _now(),
                "published_by": operator,
                "baseline_price": price,
                "currency": conf.get("currency", "CNY"),
                "sample_basis_quote_ids": quote_ids,
                "sample_basis": _deep(conf.get("participating", [])),
                "excluded_basis": _deep(conf.get("excluded", [])),
                "excluded_amount": conf.get("excluded_amount", 0),
                "rule_batch_refs": rule_refs,
                "caliber_text": conf.get("caliber_text", ""),
                "consistent": consistent,
            }
            row["publication"] = publication
            row["status"] = "已发布"

            baseline = db.find("spec_baseline", int(row["baseline_id"])) if row.get("baseline_id") else None
            if baseline is not None:
                baseline["基线价格"] = price
                baseline["status"] = "已生效"
                baseline["updated_at"] = publication["published_at"]
                baseline["current_confirmation"] = _deep(conf)
                baseline["publication"] = _deep(publication)
                self._upsert_generic_baseline(baseline, int(row["id"]))
            return _deep(row), "基线已发布，价格与样本依据来自同一次确认"

    # ---------------- 辅助 ----------------

    def _split_results(self, results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        participating: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        for item in results:
            quote_snapshot = {
                "quote_id": item.get("quote_id"),
                "报价编号": item.get("报价编号", ""),
                "站点名称": item.get("站点名称", ""),
                "报价金额": item.get("报价金额"),
                "input": item.get("input", {}),
                "normalized": item.get("normalized", {}),
                "actual_spec": item.get("actual_spec", ""),
                "matched_rule_ref": item.get("matched_rule_ref", ""),
                "rule_version": (item.get("matched_rule") or {}).get("rule_version", ""),
            }
            if item.get("comparable"):
                participating.append(quote_snapshot)
            else:
                verdict = item.get("verdict") or {}
                quote_snapshot["reason"] = verdict.get("reason") or "与基线规格口径不可比"
                quote_snapshot["mismatches"] = verdict.get("mismatches", [])
                quote_snapshot["rule_evaluations"] = [
                    {
                        "rule": f'{e.get("rule_code")}@{e.get("rule_version")}',
                        "规则名称": e.get("规则名称", ""),
                        "命中": e.get("命中"),
                        "failed_checks": e.get("failed_checks", []),
                    }
                    for e in item.get("evaluations", [])
                ]
                excluded.append(quote_snapshot)
        return participating, excluded

    @staticmethod
    def _sum_amount(quotes: list[dict[str, Any]]) -> float:
        total = 0.0
        for q in quotes:
            value = q.get("报价金额")
            try:
                total += float(value)
            except (TypeError, ValueError):
                continue
        return round(total, 2)

    @staticmethod
    def _caliber_text(caliber: dict[str, Any]) -> str:
        if not caliber:
            return ""
        unit = caliber.get("单瓶容量ml")
        try:
            unit_text = f"{float(unit):g}ml" if unit not in (None, "") else ""
        except (TypeError, ValueError):
            unit_text = str(unit)
        if unit_text:
            return (
                f'{caliber.get("商品标识", "")} / {caliber.get("规格口径", caliber.get("caliber_code", ""))}'
                f'（{caliber.get("包装形式", "")} × {caliber.get("数量", "")} × {unit_text}）'
            )
        return str(caliber.get("规格口径", ""))

    def _caliber_from_spec(self, spec: str, product: str) -> dict[str, Any]:
        from app.services.spec_engine import parse_spec_text
        parsed = parse_spec_text(spec)
        return {
            "caliber_code": "",
            "规格口径": spec,
            "商品标识": product,
            "包装形式": parsed["包装形式"],
            "数量": parsed["数量"] or 1,
            "单瓶容量ml": parsed["单瓶容量ml"],
        }

    def _upsert_generic_baseline(self, baseline: dict[str, Any], round_id: int | None = None) -> None:
        """把发布结果同步到通用 price_baseline 表，保持价格基线库列表一致。"""
        rows = store.rows("price_baseline")
        target = None
        generic_id = baseline.get("generic_entry_id")
        if generic_id:
            target = store.find("price_baseline", int(generic_id))
        if target is None:
            for row in rows:
                if row.get("商品标识") == baseline.get("商品标识") and row.get("归一规格") == baseline.get("归一规格"):
                    target = row
                    break
        if target is None:
            bid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            target = {"id": bid}
            rows.append(target)
        target.update({
            "商品标识": baseline.get("商品标识", ""),
            "归一规格": baseline.get("归一规格", "单瓶500ml"),
            "基线价格": f'{float(baseline["基线价格"]):.2f}',
            "采样窗口": baseline.get("采样窗口", "7d"),
            "更新时间": datetime.now(timezone.utc).date().isoformat(),
            "status": "已生效",
            "pending": False,
            "abnormal": False,
            "spec_baseline_id": baseline.get("id"),
            "last_round_id": round_id,
        })


workflow = WorkflowService()
workflow.ensure_seed()
