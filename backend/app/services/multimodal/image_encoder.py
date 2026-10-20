"""图像编码器（0.10.0 以文搜图）：图片 → 向量、文本 → 向量。

## 为什么是抽象基类（依赖倒置 + 开闭原则）
「以文搜图」要求**文本向量与图像向量落在同一个向量空间**，否则无法比对。
项目里可用的编码方案有两条，且都不是万能：

  1. `ChineseCLIPEncoder` —— 任务指定的 `OFA-Sys/chinese-clip-vit-base-patch16`，
     图文同空间、本地推理不花钱。但需要 torch + chinese-clip 两个重依赖
     （本机 chinese-clip 无法通过 pip 安装，因此默认不可用）。
  2. `CaptionEncoder` —— 用视觉模型给图片生成一句中文图注，再用文本向量模型编码图注。
     零本地模型依赖，走项目统一的阿里云通道；代价是丢失图片里的视觉细节。

两者可互换（里氏替换），`create_image_encoder()` 按 `IMAGE_ENCODER` 配置与依赖可用性挑选。
将来接别的编码器只需新增子类，调用方不用改（开闭原则）。

## 向量空间一致性约束（重要）
`ImageStore` 里所有向量必须来自**同一个编码器**。切换编码器后，
旧的图像向量与新向量不同维/不同空间，检索会失效——因此换编码器必须清空图像集合重建。
"""
from __future__ import annotations

import abc
import base64
import io
import logging
from typing import List, Optional

from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)

# 图注生成的提示词：要求一句中文、突出可检索的关键实体
CAPTION_PROMPT = (
    "请用一句中文描述这张图片的内容，聚焦其中的院校名称、专业名称、表格数据、"
    "课程体系、流程步骤等可检索信息，40 字以内，不要评价图片质量。"
)


class BaseImageEncoder(abc.ABC):
    """图像 / 文本编码器抽象。实现方必须保证 encode_text 与 encode_image 同空间。"""

    #: 编码器标识，写入 Chroma metadata，便于排查「这批向量是谁编的」
    name: str = "base"

    @abc.abstractmethod
    def encode_image(self, image_bytes: bytes) -> Optional[List[float]]:
        """图片字节 → 向量；失败返回 None。"""

    @abc.abstractmethod
    def encode_text(self, text: str) -> Optional[List[float]]:
        """文本 → 向量；失败返回 None。"""

    def available(self) -> bool:
        """实现方是否可用（依赖缺失 / Key 缺失时返回 False）。"""
        return True


class ChineseCLIPEncoder(BaseImageEncoder):
    """Chinese-CLIP 编码器（任务指定方案，需 torch + chinese-clip）。

    依赖通过函数内 import 延迟加载：没装 chinese-clip 时 `available()` 返回 False，
    不影响服务启动（项目里其他模块也沿用同样的延迟导入策略）。
    """

    name = "chinese-clip"

    def __init__(self, model_name: str = "OFA-Sys/chinese-clip-vit-base-patch16") -> None:
        self._model_name = model_name
        self._model = None
        self._processor = None
        self._torch = None
        self._loaded = False

    # ---------------- 模型加载（懒加载 + 单例缓存） ----------------

    def _ensure_model(self) -> bool:
        if self._loaded:
            return self._model is not None
        self._loaded = True
        try:
            import torch
            from chinese_clip import ChineseCLIPModel, ChineseCLIPProcessor  # noqa: WPS433

            self._torch = torch
            self._model = ChineseCLIPModel.from_pretrained(self._model_name)
            self._processor = ChineseCLIPProcessor.from_pretrained(self._model_name)
            self._model.eval()
            logger.info("[MM] Chinese-CLIP 加载完成：%s", self._model_name)
            return True
        except Exception as exc:  # noqa: BLE001 依赖缺失/模型下载失败
            logger.info("[MM] Chinese-CLIP 不可用（%s），将使用其他编码器", exc.__class__.__name__)
            self._model = None
            return False

    def available(self) -> bool:
        return self._ensure_model()

    # ---------------- 编码 ----------------

    def encode_image(self, image_bytes: bytes) -> Optional[List[float]]:
        if not self._ensure_model():
            return None
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            inputs = self._processor(images=image, return_tensors="pt")
            feats = self._model.get_image_features(**inputs)
            return self._to_list(feats)
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] Chinese-CLIP 图像编码失败：%s", exc.__class__.__name__)
            return None

    def encode_text(self, text: str) -> Optional[List[float]]:
        if not self._ensure_model() or not text:
            return None
        try:
            inputs = self._processor(text=[text], return_tensors="pt", padding=True)
            feats = self._model.get_text_features(**inputs)
            return self._to_list(feats)
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] Chinese-CLIP 文本编码失败：%s", exc.__class__.__name__)
            return None

    def _to_list(self, feats) -> List[float]:
        """张量 → list[float]（CLIP 输出已归一化，直接取值即可）。"""
        return feats[0].detach().cpu().tolist()


class CaptionEncoder(BaseImageEncoder):
    """图注编码器（兜底方案）：视觉模型生成图注 → 文本向量模型编码。

    零本地模型依赖，走项目统一的阿里云 OpenAI 兼容通道。
    适用于 Chinese-CLIP 装不上的环境（本机当前就是这种情况）。
    """

    name = "caption"

    def __init__(self, vlm_model: str = "", embed_model: str = "") -> None:
        self._vlm_model = vlm_model or settings.MULTIMODAL_VLM_MODEL
        self._embed_model = embed_model or settings.ALI_EMBED_MODEL
        self._client = None
        self._caption_cache: dict = {}

    def available(self) -> bool:
        return bool(_get_api_key())

    # ---------------- 编码 ----------------

    def encode_image(self, image_bytes: bytes) -> Optional[List[float]]:
        """图片 → 图注 → 向量。图注按内容哈希缓存，避免重复调用视觉模型。"""
        caption = self._caption(image_bytes)
        if not caption:
            return None
        return self.encode_text(caption)

    def encode_text(self, text: str) -> Optional[List[float]]:
        client = self._get_client()
        if client is None or not text:
            return None
        try:
            resp = client.embeddings.create(
                model=self._embed_model,
                input=[text],
                dimensions=_text_dimension(),
            )
            return list(resp.data[0].embedding)
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] 图注向量编码失败：%s", exc.__class__.__name__)
            return None

    # ---------------- 内部工具 ----------------

    def _caption(self, image_bytes: bytes) -> str:
        """视觉模型生成一句中文图注（带缓存）。"""
        key = str(hash(image_bytes))
        if key in self._caption_cache:
            return self._caption_cache[key]

        client = self._get_client()
        if client is None:
            return ""
        url = _to_data_url(image_bytes)
        if not url:
            return ""
        try:
            resp = client.chat.completions.create(
                model=self._vlm_model,
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": url}},
                    {"type": "text", "text": CAPTION_PROMPT},
                ]}],
                max_tokens=120,
                temperature=0,
            )
            caption = (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] 图注生成失败：%s", exc.__class__.__name__)
            caption = ""

        self._caption_cache[key] = caption
        return caption

    def _get_client(self):
        if self._client is not None:
            return self._client
        key = _get_api_key()
        if not key:
            return None
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=key, base_url=settings.ALI_BASE_URL)
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] OpenAI 客户端创建失败：%s", exc.__class__.__name__)
            return None
        return self._client


# ------------------------------------------------------------ 工厂与工具


def _get_api_key() -> str:
    import os

    return os.getenv("Ali_API_KEY", "")


def _text_dimension() -> int:
    """文本向量维度：优先对齐已有文本集合，保证与文本 RAG 同空间。"""
    try:
        from app.services.rag import rag_service

        return rag_service._collection_dimension() or settings.ALI_EMBED_DIMENSION
    except Exception:  # noqa: BLE001
        return settings.ALI_EMBED_DIMENSION


def _to_data_url(image_bytes: bytes) -> str:
    """图片字节 → base64 data URL，超长边先缩放控制请求体积。"""
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


def create_image_encoder() -> BaseImageEncoder:
    """按配置与依赖可用性挑选编码器。

    `IMAGE_ENCODER` 取值：
      · `auto`（默认）—— Chinese-CLIP 可用就用它，否则用 CaptionEncoder
      · `clip`          —— 强制 Chinese-CLIP（不可用则回落 CaptionEncoder）
      · `caption`       —— 强制 CaptionEncoder

    注意：图像集合里的向量必须来自同一编码器，切换后需清空图像集合重建。
    """
    preference = (settings.IMAGE_ENCODER or "auto").strip().lower()
    clip = ChineseCLIPEncoder()
    if preference in ("auto", "clip") and clip.available():
        return clip
    return CaptionEncoder()
