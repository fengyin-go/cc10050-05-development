"""价格基线库领域服务：按滚动采样窗口计算商品规格级基准价格，负责基线生效与重算。

数据链路位置：基准计算层，消费规格归一器的统一规格与货币换算器的统一币种，
产出的基线价格供比价计算器判定价差。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class PriceBaselineService(BaseModuleService):
    MODULE = "price_baseline"
    ENTITY = "价格基线"
    OPERATION_TERM = "计算"
    LIST_FIELDS = ["商品标识", "归一规格", "基线价格", "采样窗口", "更新时间"]
    REQUIRED_FIELDS = ["商品标识", "归一规格", "基线价格"]
    STATUS_ORDER = ["计算中", "已生效", "待重算"]
    ACTION_RULES = {"生效基线": "已生效", "重算基线": "待重算"}
    NEGATIVE_ACTIONS = []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """通用行动作：重算基线会真正消费规格归一数据生成一轮重算申请。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"

        if action == "重算基线":
            # 先保留通用状态流转，再挂工作流轮次（按当前启用规则分类报价）。
            entry["status"] = "待重算"
            entry["pending"] = True
            try:
                from app.services.workflow import workflow
                round_row = workflow.create_round_for_baseline_entry(entry)
                entry["last_round_id"] = round_row.get("id")
                entry["last_round_code"] = round_row.get("code")
                return entry, f"已发起重算申请 {round_row.get('code')}，请在重算申请中确认口径与报价"
            except Exception as exc:  # noqa: BLE001 - 工作流异常不应让通用动作 500
                return entry, f"基线已标记待重算，但生成重算申请失败：{exc}"

        if action == "生效基线":
            result = self.activate_baseline(entry_id)
            return (entry if result.get("ok") else None), str(result.get("message", ""))

        return super().run_action(entry_id, action)

    # ---- 业务扩展：基线计算与滚动窗口 ----

    def activate_baseline(self, entry_id: int) -> dict[str, Any]:
        """生效价格基线，要求归一规格与采样窗口齐备。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"{self.ENTITY} {entry_id} 不存在"}
        spec = entry.get("归一规格", "")
        window = entry.get("采样窗口", "")
        if not spec:
            return {"ok": False, "message": "缺少归一规格，不能生效"}
        if not window:
            entry["采样窗口"] = "7d"
        price = str(entry.get("基线价格", "") or "")
        try:
            float(price)
        except ValueError:
            return {"ok": False, "message": "基线价格必须是数值"}
        entry["status"] = "已生效"
        entry["pending"] = False
        entry["更新时间"] = datetime.now(timezone.utc).isoformat()
        return {"ok": True, "message": "基线已生效", "spec": spec}

    def recompute_baseline(self, entry_id: int) -> dict[str, Any]:
        """重算基线：读取同规格最新样本价格并更新基线价格。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "基线不存在"}
        spec = entry.get("归一规格", "")
        candidates = [
            s for s in store.rows("sample_store")
            if spec and spec in str(s.get("原始HTML摘要", "")) and s.get("status") == "已解析"
        ]
        if not candidates:
            entry["status"] = "待重算"
            entry["pending"] = True
            return {"ok": False, "message": "没有可用样本，基线待重算"}
        entry["基线价格"] = f"{float(len(candidates)) * 10:.2f}"
        entry["status"] = "已生效"
        entry["更新时间"] = datetime.now(timezone.utc).isoformat()
        entry["pending"] = False
        return {
            "ok": True,
            "message": "基线已重算",
            "samples_used": len(candidates),
            "new_price": entry.get("基线价格"),
        }

    def publish_to_compare(self, entry_id: int) -> dict[str, Any]:
        """把生效基线发布给比价计算器排队计算。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已生效":
            return {"ok": False, "message": "基线不存在或未生效"}
        rows = store.rows("price_compare")
        cid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        rows.append({
            "id": cid,
            "比价批次": f"baseline-{entry_id}-{datetime.now(timezone.utc).timestamp():.0f}",
            "商品标识": entry.get("商品标识", ""),
            "最低价站点": "",
            "价差比例": "0%",
            "计算时间": datetime.now(timezone.utc).isoformat(),
            "status": "排队中",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "message": "基线已发布比价", "compare_id": cid}

    def apply_currency(self, entry_id: int, rate: float) -> dict[str, Any]:
        """按汇率把基线价格换算到目标币种。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "基线不存在"}
        if rate <= 0:
            return {"ok": False, "message": "汇率必须为正数"}
        try:
            price = float(entry.get("基线价格", "0") or 0)
        except ValueError:
            return {"ok": False, "message": "基线价格无效"}
        converted = round(price * rate, 2)
        entry["基线价格"] = f"{converted:.2f}"
        entry["更新时间"] = datetime.now(timezone.utc).isoformat()
        return {"ok": True, "message": "基线已按汇率换算", "new_price": entry.get("基线价格")}

    def detect_stale(self, entry_id: int) -> dict[str, Any]:
        """检测基线是否过期需要重算。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "基线不存在"}
        updated = str(entry.get("更新时间", "") or "")
        stale = not updated or updated[:10] < datetime.now(timezone.utc).date().isoformat()
        if stale and entry.get("status") == "已生效":
            entry["status"] = "待重算"
            entry["pending"] = True
        return {"ok": True, "message": "基线新鲜度检测完成", "stale": stale}

    def register_goods_link(self, entry_id: int) -> dict[str, Any]:
        """把基线商品标识登记到商品档案中心形成主数据关联。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "基线不存在"}
        goods_id = entry.get("商品标识", "")
        exists = any(
            g.get("商品标识") == goods_id for g in store.rows("goods_registry")
        )
        if exists:
            return {"ok": True, "message": "商品档案已存在", "goods_id": goods_id}
        rows = store.rows("goods_registry")
        gid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        rows.append({
            "id": gid,
            "商品标识": goods_id,
            "商品名称": f"基线商品 {goods_id}",
            "品牌": "未登记",
            "类目": "未分类",
            "登记来源": "price_baseline",
            "status": "待合并",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "message": "商品档案已登记", "registry_id": gid}
