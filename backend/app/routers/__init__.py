"""业务路由汇总：工作流专用路由优先注册，避免被通用 /{module} 动态路径抢先匹配。"""
from __future__ import annotations

from app.routers import resource, workflow

ROUTERS = [workflow, resource]
