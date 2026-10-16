"""多模态大模型客户端（0.10.0）：图片 + 问题 → 文字回答。

## 单一职责
只负责「把图片和问题交给视觉语言模型并拿回文字」，
不负责检索图片、不负责判断是否该走多模态。

## 通道统一
与其他 LLM 调用一致，走阿里云 OpenAI 兼容接口（`Ali_API_KEY` + `ALI_BASE_URL`）。
模型用 `qwen3.7-flash`（0.10.0 起替代额度耗尽的 `qwen3.7-flash-2026-07-15`，
原生支持图文输入）。

## 降级
模型不可用 / 超时 / 返回空 → 返回空字符串，由上层决定是否回落到文本链路，
不向上抛异常（避免一次 VLM 失败把整个问答打挂）。
"""
from __future__ import annotations

import base64
import io
import logging
import os
from typing import List, Optional

from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)

# 防幻觉 Prompt：只允许依据给定的图片内容回答
VLM_ANSWER_PROMPT = """你是高考志愿填报助手。请仔细观察下面给出的图片，然后回答用户的问题。

要求：
1. 只依据图片中能看到的信息回答，不要补充图片里没有的数字或事实。
2. 图片是课程体系图、培养方案、校园照片、流程图一类资料时，
   请把其中的关键信息（课程名、学分、学期、步骤、数据）有条理地列出来。
3. 如果图片里没有用户问的信息，明确说明"图片中未包含该信息"。
4. 禁止使用"通常、大概、一般来说"来推测。

用户提问：{question}
"""


class VLMClient:
    """视觉语言模型调用封装。"""

    def __init__(self, model: str = "", api_key: str = "", base_url: str = "") -> None:
        self._model = model or settings.MULTIMODAL_VLM_MODEL
        self._api_key = api_key or os.getenv("Ali_API_KEY", "")
        self._base_url = base_url or settings.ALI_BASE_URL
        self._client = None

    def available(self) -> bool:
        return bool(self._api_key)

    # ---------------- 对外唯一入口 ----------------

    def generate_with_images(self, question: str, images: List[bytes],
                             max_tokens: int = 800) -> str:
        """把问题与多张图片交给视觉模型，返回文字回答；失败返回空串。

        :param question: 用户问题
        :param images:   图片字节列表（已按相关度排序，最多取前 N 张）
        :param max_tokens: 回答长度上限
        """
        if not question or not images:
            return ""
        client = self._get_client()
        if client is None:
            return ""

        content: List[dict] = []
        for raw in images[: settings.MULTIMODAL_TOP_K]:
            url = self._to_data_url(raw)
            if url:
                content.append({"type": "image_url", "image_url": {"url": url}})
        if not content:
            return ""
        content.append({"type": "text", "text": VLM_ANSWER_PROMPT.format(question=question)})

        try:
            resp = client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": content}],
                max_tokens=max_tokens,
                temperature=0.1,
                top_p=0.3,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001 超时/限流/额度都按失败处理
            logger.info("[MM] VLM 调用失败：%s %s", exc.__class__.__name__, str(exc)[:150])
            return ""

    # ---------------- 内部工具 ----------------

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            return None
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] OpenAI 客户端创建失败：%s", exc.__class__.__name__)
            return None
        return self._client

    @staticmethod
    def _to_data_url(image_bytes: bytes) -> str:
        """图片字节 → base64 data URL，超长边先缩放（控制请求体积与耗时）。"""
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            side = int(settings.IMAGE_MAX_SIDE)
            longest = max(img.size)
            if longest > side:
                ratio = side / longest
                img = img.resize((max(1, int(img.size[0] * ratio)),
                                  max(1, int(img.size[1] * ratio))), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:  # noqa: BLE001
            return ""
