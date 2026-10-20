"""云端「心理师 / 画像构建师」（0.13.0）。

## 定位
系统里有两个 AI 角色，职责不同：

| 角色 | 模型 | 用途 | 特点 |
|---|---|---|---|
| 志愿助手 | 本地 `qwen3:4b` | 政策、分数、院校查询 | 毫秒级、数据不出本机、走 Function Calling |
| 心理师 | 云端 `qwen3.7-flash` | 多轮谈心、疏导焦虑、采集画像 | 情感推理强、需要多轮上下文 |

## 为什么强制云端、不降级到本地
本地 4b 的情感理解与长对话一致性明显不足（容易说教、丢失前文）。
心理疏导说错话的代价远高于慢几秒，因此这里**只走 Ali 通道**，
失败就明确报错让前端提示「稍后再试」，而不是悄悄换成小模型糊弄用户。

## 为什么单独一个 Service 而不是塞进 rag_service
`rag_service` 是「检索增强问答」，本类是「无检索的纯对话 + 画像注入」，
两者共享的只有「读画像」这一件事。拆开后：
  · 改心理师话术不会碰到 RAG 链路（开闭）；
  · 单测可以直接注入桩通道（依赖倒置）。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 心理师人设与安全边界
COUNSELOR_SYSTEM_PROMPT = """你是一位温和、专业的高考志愿陪伴顾问，兼具生涯规划与心理疏导能力。

【你的角色】
1. 先共情、再建议：考生表达焦虑、迷茫、家庭分歧时，先接住情绪，再给可执行的小步骤。
2. 通过聊天**自然地**了解他：兴趣方向、擅长科目、对地域与学费的偏好、家庭期待、对未来工作的想象。
3. 不要一次问太多问题，每轮最多问 1-2 个，像朋友聊天而不是填表。
4. 回答务实，不说空话、不灌鸡汤、不做心理诊断（不贴「你有焦虑症」这类标签）。

【安全边界】
1. 你**不能**给出精确的分数线、位次、学费数字——这些由志愿助手查数据库。
   需要具体数据时，引导他去「AI 志愿助手」提问。
2. 遇到严重的心理困扰（自伤、持续失眠、极端情绪），
   明确建议寻求学校心理老师或专业机构的帮助，不要试图独自处理。
3. 不评判考生的家庭与成绩，不制造新的焦虑。

【语言】
中文，200 字以内，口语化，可以用一两个换行分段。
"""

#: 有画像时的补充说明（让云端模型知道该"顺着"哪些特征聊）
COUNSELOR_PROFILE_HINT = """
【已知的考生画像】（生成于 {updated}，用于避免重复提问，不要直接念给考生听）
{summary}
"""


class CounselorService:
    """多轮心理疏导对话（强制云端通道）。"""

    def __init__(self, channel: Any = None) -> None:
        """
        :param channel: 具备 `chat_messages(messages, ...)` 的通道对象；
                        默认使用 `AliLLMChannel`（**不降级到本地**）
        """
        self._channel = channel

    # ---------------- 通道 ----------------

    def _get_channel(self):
        if self._channel is None:
            from app.services.llm_client import AliLLMChannel

            self._channel = AliLLMChannel()
        return self._channel

    def available(self) -> bool:
        try:
            return bool(self._get_channel().available())
        except Exception:  # noqa: BLE001
            return False

    # ---------------- 主入口 ----------------

    def chat(
        self,
        messages: List[Dict[str, str]],
        profile_summary: str = "",
        profile_updated: str = "",
        extra_context: str = "",
    ) -> Dict[str, Any]:
        """执行一轮多轮对话。

        :param messages: 历史消息（不含 system），形如
                         `[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]`
        :param profile_summary: `user_profiles.summary_text`
        :return: {"answer", "source", "model", "elapsed_ms", "profile_injected", "error"}
        """
        from app.config import settings

        start = time.time()
        history = self._trim(messages)
        if not history:
            return self._result("", error="没有收到消息内容")

        if not self.available():
            logger.warning("[COUNSELOR] 云端通道不可用（未配置 Ali_API_KEY 或初始化失败）")
            return self._result("", error="云端心理师通道不可用，请检查 ALI_API_KEY 配置")

        system = COUNSELOR_SYSTEM_PROMPT
        if profile_summary:
            system += COUNSELOR_PROFILE_HINT.format(
                updated=profile_updated or "未知", summary=profile_summary
            )
        if extra_context:
            system += f"\n【附加信息】\n{extra_context}\n"

        payload: List[Dict[str, str]] = [{"role": "system", "content": system}]
        payload.extend(history)

        try:
            text = self._get_channel().chat_messages(
                payload,
                temperature=0.6,      # 情绪陪伴需要一点温度，但不能太飘
                max_tokens=800,
                top_p=0.9,
                timeout=settings.COUNSELOR_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[COUNSELOR] 调用异常：%s", exc.__class__.__name__)
            return self._result("", error=f"云端心理师调用失败：{exc.__class__.__name__}")

        if not text:
            return self._result("", error="云端心理师没有返回内容，请稍后重试")

        elapsed = int((time.time() - start) * 1000)
        model = getattr(self._get_channel(), "model", "")
        logger.info(
            "[COUNSELOR] 回复完成 model=%s %dms 画像注入=%s 历史=%d 条",
            model, elapsed, bool(profile_summary), len(history),
        )
        return {
            "answer": text,
            "source": "counselor:ali",
            "model": model,
            "elapsed_ms": elapsed,
            "profile_injected": bool(profile_summary),
            "error": "",
        }

    # ---------------- 内部工具 ----------------

    @staticmethod
    def _trim(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """裁剪历史：只保留最近 N 条，且过滤非法角色（防止前端注入 system 覆盖人设）。"""
        from app.config import settings

        clean: List[Dict[str, str]] = []
        for m in messages or []:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "").strip()
            content = str(m.get("content") or "").strip()
            if role not in ("user", "assistant") or not content:
                continue
            clean.append({"role": role, "content": content[:4000]})
        limit = max(2, int(settings.COUNSELOR_MAX_HISTORY or 20))
        return clean[-limit:]

    @staticmethod
    def _result(answer: str, error: str = "") -> Dict[str, Any]:
        return {
            "answer": answer,
            "source": "counselor:error" if error else "counselor:ali",
            "model": "",
            "elapsed_ms": 0,
            "profile_injected": False,
            "error": error,
        }


__all__ = ["CounselorService", "COUNSELOR_SYSTEM_PROMPT"]
