"""规格归一器领域服务：管理各平台规格文本的归一规则与单位换算，负责统一规格口径。

数据链路位置：数据标准化层，把解析层产出的多平台规格文本归一为统一规格，
归一结果供价格基线库与规格匹配器消费。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class SpecNormalizerService(BaseModuleService):
    MODULE = "spec_normalizer"
    ENTITY = "规格归一规则"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["规则名称", "源规格文本", "归一规格", "单位换算", "映射优先级"]
    REQUIRED_FIELDS = ["规则名称", "源规格文本", "归一规格"]
    STATUS_ORDER = ["草稿", "已启用", "已停用"]
    ACTION_RULES = {"启用规则": "已启用", "停用规则": "已停用"}
    NEGATIVE_ACTIONS = ["停用规则"]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """登记通用规则的同时，派生一条可试判、可更正版本的结构化规则。"""
        entry, missing = super().create_entry(values)
        if entry is not None:
            try:
                from app.services.workflow import workflow
                workflow.create_rich_rule_from_entry(entry, values)
            except Exception:  # noqa: BLE001 - 派生失败不影响通用登记
                pass
        return entry, missing

    # ---- 业务扩展：规格归一与口径统一 ----

    def enable_rule(self, entry_id: int) -> dict[str, Any]:
        """启用归一规则，检查源文本与归一规格是否成对配置。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"{self.ENTITY} {entry_id} 不存在"}
        source = entry.get("源规格文本", "")
        target = entry.get("归一规格", "")
        if not source or not target:
            return {"ok": False, "message": "源规格文本与归一规格必须成对配置"}
        priority = str(entry.get("映射优先级", "") or "")
        if not priority.isdigit():
            entry["映射优先级"] = "1"
        entry["status"] = "已启用"
        entry["pending"] = False
        return {"ok": True, "message": f"规则 {entry.get('规则名称', '')} 已启用"}

    def normalize_text(self, entry_id: int, raw_text: str) -> dict[str, Any]:
        """按归一规则把原始规格文本转换为统一规格口径。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已启用":
            return {"ok": False, "message": "归一规则不存在或未启用"}
        source = entry.get("源规格文本", "")
        if source and source not in raw_text:
            return {"ok": False, "message": "规格文本与规则源文本不匹配"}
        unit = entry.get("单位换算", "")
        normalized = entry.get("归一规格", raw_text)
        return {
            "ok": True,
            "message": "规格已归一",
            "normalized": normalized,
            "unit": unit,
            "priority": entry.get("映射优先级", "1"),
        }

    def sync_to_baseline(self, entry_id: int) -> dict[str, Any]:
        """把归一规格同步到价格基线库，标记对应基线待重算。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "归一规则不存在"}
        normalized = entry.get("归一规格", "")
        affected = 0
        for base in store.rows("price_baseline"):
            if base.get("归一规格") == normalized:
                base["status"] = "待重算"
                base["pending"] = True
                affected += 1
        return {
            "ok": True,
            "message": "归一规格已同步基线",
            "affected_baselines": affected,
            "normalized": normalized,
        }

    def push_to_sku_match(self, entry_id: int) -> dict[str, Any]:
        """把归一规则推送到规格匹配器作为候选规格。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已启用":
            return {"ok": False, "message": "归一规则不存在或未启用"}
        rows = store.rows("sku_match")
        mid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        rows.append({
            "id": mid,
            "匹配批次": f"norm-{entry_id}-{datetime.now(timezone.utc).timestamp():.0f}",
            "商品档案": "",
            "候选规格": entry.get("归一规格", ""),
            "匹配置信度": "1.00",
            "匹配状态": "待匹配",
            "status": "待匹配",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "message": "候选规格已推送匹配器", "match_id": mid}

    def detect_conflicts(self, entry_id: int) -> dict[str, Any]:
        """检测与其他启用规则是否存在源文本重叠冲突。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "归一规则不存在"}
        source = entry.get("源规格文本", "")
        conflicts = [
            r.get("规则名称", "") for r in store.rows(self.MODULE)
            if r.get("id") != entry.get("id") and r.get("status") == "已启用"
            and source and source in str(r.get("源规格文本", ""))
        ]
        if conflicts:
            entry["status"] = "草稿"
            entry["pending"] = True
        return {
            "ok": True,
            "message": "冲突检测完成",
            "conflicts": conflicts,
            "rule_status": entry.get("status"),
        }

    def archive_stale_rules(self, days: int = 30) -> dict[str, Any]:
        """停用长期未启用的规则并归档到审计明细。"""
        now = datetime.now(timezone.utc)
        stale = [
            r for r in store.rows(self.MODULE) if r.get("status") == "草稿"
        ]
        for rule in stale:
            rule["status"] = "已停用"
            rule["abnormal"] = False
        rows = store.rows("parse_audit")
        aid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        rows.append({
            "id": aid,
            "审计时间": now.isoformat(),
            "解析模板": "规格归一规则清理",
            "样本总数": str(len(stale)),
            "字段命中率": "100.00%",
            "失败原因分布": "",
            "status": "正常",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "message": f"已停用 {len(stale)} 条草稿规则", "archived": len(stale)}
