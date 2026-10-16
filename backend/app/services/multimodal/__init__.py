"""多模态 RAG 模块（0.10.0「以文搜图」）。

## 模块边界
本模块只做**以文搜图**一件事，不做「以图搜文」、不做「图文混合融合」。
图像通道按关键词触发：问题命中「图 / 照片 / 课程表 / 培养方案 / 校园 …」等词才启用，
其余问题仍走 0.9.1 的三路融合（图谱 + MySQL + 向量）。

## 对外导出
    ImageExtractor   从 PDF 提取嵌图（扫描件退化为按页渲染）
    ImageEncoder     图像 / 文本编码抽象（Chinese-CLIP 首选，图注方案兜底）
    ImageStore       Chroma 独立图像集合 gaokao_images 读写删
    VLMClient        视觉语言模型调用（qwen3.7-flash，图文输入）
    ImageRetriever   合成复用以上四者，对外唯一入口

## 依赖倒置
`ImageRetriever` 的四个协作者全部构造注入，测试时可整体替换为桩对象，
不需要真实 Chroma / 本地模型 / 阿里云 Key。
"""
from app.services.multimodal.image_encoder import (
    BaseImageEncoder,
    CaptionEncoder,
    ChineseCLIPEncoder,
    create_image_encoder,
)
from app.services.multimodal.image_extractor import ImageExtractor
from app.services.multimodal.image_retriever import ImageRetriever
from app.services.multimodal.image_store import ImageStore
from app.services.multimodal.vlm_client import VLMClient

__all__ = [
    "ImageExtractor",
    "BaseImageEncoder",
    "ChineseCLIPEncoder",
    "CaptionEncoder",
    "create_image_encoder",
    "ImageStore",
    "VLMClient",
    "ImageRetriever",
]
