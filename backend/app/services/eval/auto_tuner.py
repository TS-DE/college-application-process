"""自动参数调优：把诊断建议转换成**白名单内**的可执行参数变更（写回 .env 与运行时 settings）。

安全设计（★ 硬性约束）：
1. 白名单机制：只有 `PARAM_SPECS` 里登记的参数才允许被自动修改，避免模型瞎改配置；
2. 修改前备份 `backend/.env` → `backend/.env.bak.{timestamp}`，支持一键回滚；
3. 每次 apply 追加一条变更日志到 `backend/app/services/eval/changes.log`；
4. 参数生效需要重启服务（settings 在导入时读取），故返回 `need_restart=True`。
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Sequence

from app.config import settings

# 参数规格表：type / min / max，白名单与取值范围的唯一来源
PARAM_SPECS: Dict[str, Dict[str, Any]] = {
    "CHUNK_SIZE": {"type": int, "min": 200, "max": 1000, "step": 100, "desc": "切片大小"},
    "CHUNK_OVERLAP": {"type": int, "min": 50, "max": 200, "step": 25, "desc": "切片重叠"},
    "MULTI_RECALL_TOPK_PER_CHANNEL": {"type": int, "min": 10, "max": 30, "step": 5, "desc": "每通道召回数"},
    "RERANK_ENABLED": {"type": bool, "desc": "Rerank 开关"},
    "RERANK_MODEL": {"type": str, "desc": "重排序模型路径（留空用向量余弦精排）"},
    "MULTI_QUERY_ENABLED": {"type": bool, "desc": "多路召回开关"},
    "QUERY_REWRITE_ENABLED": {"type": bool, "desc": "查询重写开关"},
    "QUERY_EXPANSION_ENABLED": {"type": bool, "desc": "查询扩展开关"},
    "QUERY_DECOMPOSE_ENABLED": {"type": bool, "desc": "子查询分解开关"},
    "ADVANCED_RAG_ENABLED": {"type": bool, "desc": "高级 RAG 开关"},
    "PROMPT_VERSION": {"type": str, "allowed": {"standard", "strict"}, "desc": "防幻觉 Prompt 版本"},
}

_ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".env",
)
_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "changes.log")


@dataclass
class ParamChange:
    """一次参数变更（含前后值，便于回滚与审计）。"""

    name: str
    old_value: Any
    new_value: Any
    reason: str = ""
    report_id: str = ""
    applied: bool = False
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reason": self.reason,
            "report_id": self.report_id,
            "applied": self.applied,
            "error": self.error,
        }


@dataclass
class ApplyResult:
    """apply / rollback 的统一返回。"""

    applied: bool = False
    need_restart: bool = True
    backup: str = ""
    changes: List[ParamChange] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied": self.applied,
            "need_restart": self.need_restart,
            "backup": self.backup,
            "changes": [c.to_dict() for c in self.changes],
            "message": self.message,
        }


class AutoTuner:
    """诊断建议 → 参数变更计划 → 写回配置。"""

    def __init__(self, env_path: str = _ENV_PATH, log_path: str = _LOG_PATH) -> None:
        self.env_path = env_path
        self.log_path = log_path
        self.whitelist: List[str] = [
            p.strip() for p in str(settings.AUTO_TUNE_WHITELIST).split(",") if p.strip()
        ]

    # ---------------- 生成变更计划 ----------------

    def plan(self, diagnoses: Sequence[Any], report_id: str = "") -> List[ParamChange]:
        """把诊断项的 param_changes 草案（可能含 decrease/increase）解析为具体目标值。"""
        changes: List[ParamChange] = []
        seen = set()
        for item in diagnoses:
            raw = getattr(item, "param_changes", {}) or {}
            reason = getattr(item, "problem", "") or getattr(item, "metric", "")
            for name, target in raw.items():
                if name not in PARAM_SPECS or name not in self.whitelist or name in seen:
                    continue  # 白名单之外的参数一律丢弃
                old = getattr(settings, name, None)
                new = self._resolve(name, old, target)
                if new is None or self._same(name, old, new):
                    continue  # 已经是目标取值，无需重复变更
                changes.append(ParamChange(
                    name=name,
                    old_value=old,
                    new_value=new,
                    reason=reason,
                    report_id=report_id,
                ))
                seen.add(name)
        return changes

    def _resolve(self, name: str, old: Any, target: Any) -> Any:
        """把 decrease / increase 语义翻译成具体数值（按 white-list 的 min/max/step 收敛）。"""
        spec = PARAM_SPECS[name]
        if spec["type"] is bool:
            return 1 if str(target) not in {"0", "false", "False", ""} else 0
        if spec["type"] is str:
            return target if target in spec.get("allowed", {target}) else None
        step = spec.get("step", 1)
        current = int(old) if old is not None else spec["min"]
        if isinstance(target, int):
            value = target
        elif target == "decrease":
            value = current - step
        elif target == "increase":
            value = current + step
        else:
            value = current
        return max(spec["min"], min(spec["max"], value))

    @staticmethod
    def _same(name: str, old: Any, new: Any) -> bool:
        """归一化比较两个取值是否实质相同（bool 与 int/str 之间容错）。"""
        spec = PARAM_SPECS.get(name, {})
        if spec.get("type") is bool:
            old_b = bool(old) if not isinstance(old, bool) else old
            new_b = bool(new) if not isinstance(new, bool) else new
            return old_b == new_b
        if spec.get("type") is int:
            try:
                return int(old) == int(new)
            except (TypeError, ValueError):
                return False
        return str(old) == str(new)

    # ---------------- 应用 / 回滚 ----------------

    def apply(self, changes: Sequence[ParamChange], dry_run: bool = False) -> ApplyResult:
        """写回 .env 并同步更新内存 settings（仍需重启才完全生效）。"""
        if not settings.AUTO_TUNE_ENABLED:
            return ApplyResult(applied=False, message="AUTO_TUNE_ENABLED=0，自动调优已全局关闭")

        result = ApplyResult(changes=list(changes))
        if not changes:
            result.message = "没有需要应用的参数变更"
            return result

        if dry_run:
            result.applied = False
            result.message = "dry_run：已生成变更计划，未写入文件"
            return result

        result.backup = self._backup()
        pairs = {c.name: str(c.new_value) for c in changes}
        try:
            self._write_env(pairs)
        except Exception as exc:  # noqa: BLE001
            result.message = f"写入 .env 失败：{exc}"
            return result

        for change in result.changes:
            change.applied = True
            self._sync_settings(change.name, change.new_value)
            self._log(change, action="apply")
        result.applied = True
        result.message = f"已应用 {len(result.changes)} 项参数变更，重启服务后生效"
        return result

    def rollback(self, backup_path: str = "") -> ApplyResult:
        """回滚到最近一次备份（找不到备份则回滚 changelog 里最近一次 apply 的前值）。"""
        result = ApplyResult(need_restart=True)
        if not backup_path:
            backup_path = self._latest_backup()
        if not backup_path or not os.path.exists(backup_path):
            # 兜底：用 changes.log 里最近一次 apply 的 old_value 反向写回
            changes = self._invert_from_log()
            if not changes:
                result.message = "没有可回滚的备份或变更日志"
                return result
            return self.apply(changes)

        shutil.copy2(backup_path, self.env_path)
        for change in self._diff_from_log(backup_path):
            change.applied = True
        result.applied = True
        result.backup = backup_path
        result.message = f"已回滚到备份 {os.path.basename(backup_path)}，重启服务后生效"
        self._log(None, action=f"rollback:{os.path.basename(backup_path)}")
        return result

    def recent_changes(self, limit: int = 10) -> List[Dict[str, Any]]:
        """读取变更日志（倒序最近 N 条），供前端「变更日志」展示。"""
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        records: List[Dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                import json

                records.append(json.loads(line))
            except Exception:  # noqa: BLE001 旧格式日志直接跳过
                continue
        return list(reversed(records))

    # ---------------- 内部工具 ----------------

    def _backup(self) -> str:
        if not os.path.exists(self.env_path):
            return ""
        target = f"{self.env_path}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(self.env_path, target)
        return target

    def _latest_backup(self) -> str:
        directory = os.path.dirname(self.env_path)
        if not os.path.isdir(directory):
            return ""
        candidates = sorted(
            [os.path.join(directory, f) for f in os.listdir(directory)
             if f.startswith(os.path.basename(self.env_path) + ".bak.")],
            reverse=True,
        )
        return candidates[0] if candidates else ""

    def _write_env(self, pairs: Dict[str, str]) -> None:
        """按 KEY=VALUE 更新 .env（不存在则追加）。"""
        lines: List[str] = []
        if os.path.exists(self.env_path):
            with open(self.env_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()

        remaining = dict(pairs)
        output: List[str] = []
        for line in lines:
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key in pairs:
                output.append(f"{key}={remaining.pop(key)}")
            else:
                output.append(line)
        for key, value in remaining.items():
            output.append(f"{key}={value}")

        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(output) + "\n")

    @staticmethod
    def _sync_settings(name: str, value: Any) -> None:
        """同步修改内存中的 settings，使当前进程立即部分生效。"""
        spec = PARAM_SPECS.get(name, {})
        if spec.get("type") is bool:
            setattr(settings, name, str(value) not in {"0", "false", "False", ""})
        elif spec.get("type") is int:
            setattr(settings, name, int(value))
        else:
            setattr(settings, name, value)

    def _log(self, change: ParamChange | None, action: str) -> None:
        import json

        record: Dict[str, Any] = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
        }
        if change:
            record.update(change.to_dict())
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _diff_from_log(self, backup_path: str) -> List[ParamChange]:
        """回滚时从日志里还原变更前后值（用于回写 changelog 展示）。"""
        changes: List[ParamChange] = []
        for record in self.recent_changes(limit=50):
            if record.get("action") != "apply":
                continue
            changes.append(ParamChange(
                name=record.get("name", ""),
                old_value=record.get("old_value"),
                new_value=record.get("new_value"),
                reason=record.get("reason", ""),
                report_id=record.get("report_id", ""),
            ))
        return changes

    def _invert_from_log(self) -> List[ParamChange]:
        """用日志里最近一批 apply 的 old_value 生成反向变更。"""
        inverted: List[ParamChange] = []
        seen = set()
        for record in self.recent_changes(limit=50):
            if record.get("action") != "apply":
                continue
            name = record.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            inverted.append(ParamChange(
                name=name,
                old_value=record.get("new_value"),
                new_value=record.get("old_value"),
                reason="回滚至变更前的值",
                report_id=record.get("report_id", ""),
            ))
        return inverted
