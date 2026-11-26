"""试判 / 规则更正 / 重算申请 / 确认发布 的专用接口。

页面主要通过这些接口完成跨模块工作流；通用 /api/{module} 资源接口保持不变。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.workflow import workflow

router = APIRouter(tags=["试判与重算工作流"])


class CorrectPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    operator: str | None = None


class TrialPayload(BaseModel):
    rule_ids: list[int] = Field(default_factory=list)
    rule_versions: dict[str, str] = Field(default_factory=dict)
    samples: list[dict[str, Any]] = Field(default_factory=list)
    quote_ids: list[int] = Field(default_factory=list)
    use_product_quotes: bool = False
    product: str | None = None
    baseline_id: int | None = None
    caliber: dict[str, Any] | None = None
    operator: str | None = None


class RoundFromTrialPayload(BaseModel):
    trial_id: int
    baseline_id: int | None = None


class ConfirmPayload(BaseModel):
    operator: str | None = None


# ---------- 规则与报价 ----------

@router.get("/api/spec-rules")
def get_spec_rules(product: str | None = None) -> dict[str, Any]:
    return {"items": workflow.list_rules(product)}


@router.get("/api/spec-rules/{rule_id}")
def get_spec_rule(rule_id: int) -> dict[str, Any]:
    rule = workflow.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    return rule


@router.post("/api/spec-rules/{rule_id}/correct")
def correct_spec_rule(rule_id: int, payload: CorrectPayload) -> dict[str, Any]:
    rule, message = workflow.correct_rule(rule_id, payload.values, payload.operator or "数据工程组")
    return {"ok": rule is not None, "message": message, "entry": rule}


@router.get("/api/price-quotes")
def get_price_quotes(product: str | None = None) -> dict[str, Any]:
    return {"items": workflow.list_quotes(product)}


@router.post("/api/price-quotes")
def create_price_quote(payload: CorrectPayload) -> dict[str, Any]:
    quote = workflow.create_quote(payload.values)
    return {"ok": True, "message": "报价样品已登记", "entry": quote}


# ---------- 基线 ----------

@router.get("/api/spec-baselines")
def get_spec_baselines() -> dict[str, Any]:
    return {"items": workflow.list_baselines()}


@router.get("/api/spec-baselines/{baseline_id}")
def get_spec_baseline(baseline_id: int) -> dict[str, Any]:
    baseline = workflow.get_baseline(baseline_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail="基线不存在")
    return baseline


@router.post("/api/spec-baselines/{baseline_id}/recompute")
def recompute_spec_baseline(baseline_id: int, payload: ConfirmPayload | None = None) -> dict[str, Any]:
    try:
        round_row = workflow.recompute_preview(baseline_id, confirm=False)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "message": "已按当前启用规则生成新一轮复算", "entry": round_row, "round": round_row}


# ---------- 试判 ----------

@router.post("/api/trial/run")
def run_trial(payload: TrialPayload) -> dict[str, Any]:
    record = workflow.run_trial(payload.model_dump(exclude_none=False))
    return {"ok": True, "message": "试判完成", "entry": record, "trial": record}


@router.get("/api/trial/{trial_id}")
def get_trial(trial_id: int) -> dict[str, Any]:
    record = workflow.get_trial(trial_id)
    if record is None:
        raise HTTPException(status_code=404, detail="试判记录不存在")
    return record


# 兼容按模块命名空间调用的入口
@router.post("/api/spec_normalizer/trial")
def run_trial_alias(payload: TrialPayload) -> dict[str, Any]:
    return run_trial(payload)


# ---------- 重算申请轮次 ----------

@router.get("/api/recalc-rounds")
def get_rounds(baseline_id: int | None = None) -> dict[str, Any]:
    return {"items": workflow.list_rounds(baseline_id)}


@router.post("/api/recalc-rounds")
def create_round(payload: RoundFromTrialPayload) -> dict[str, Any]:
    row, message = workflow.create_round_from_trial(payload.trial_id, payload.baseline_id)
    return {"ok": row is not None, "message": message, "entry": row, "round": row}


@router.get("/api/recalc-rounds/{round_id}")
def get_round(round_id: int) -> dict[str, Any]:
    row = workflow.get_round(round_id)
    if row is None:
        raise HTTPException(status_code=404, detail="重算申请不存在")
    return row


@router.post("/api/recalc-rounds/{round_id}/confirm")
def confirm_round(round_id: int, payload: ConfirmPayload | None = None) -> dict[str, Any]:
    operator = payload.operator if payload else None
    row, message = workflow.confirm_round(round_id, operator or "值班员")
    return {"ok": row is not None and bool(row.get("confirmation")), "message": message, "entry": row, "round": row}


@router.post("/api/recalc-rounds/{round_id}/publish")
def publish_round(round_id: int, payload: ConfirmPayload | None = None) -> dict[str, Any]:
    operator = payload.operator if payload else None
    row, message = workflow.publish_round(round_id, operator or "值班员")
    ok = row is not None and bool(row.get("publication"))
    return {"ok": ok, "message": message, "entry": row, "round": row}
