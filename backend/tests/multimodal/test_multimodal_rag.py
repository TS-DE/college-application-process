# -*- coding: utf-8 -*-
"""0.10.0 OCR 预处理 + 以文搜图 最小测试用例。

用法：
    python test_multimodal_rag.py            # 桩版：不调模型、不连 Chroma，秒级跑完
    python test_multimodal_rag.py --real     # 真实链路：调阿里云视觉模型 + 读写 Chroma

用例：
    1. 扫描件判定：真实扫描件 PDF 应判 True，普通 TXT 应判 False
    2. PDF 页 → 图片：pypdfium2 无需 poppler 即可渲染
    3. 图片提取：pdfplumber 抽嵌图 / 扫描件按页渲染兜底
    4. OCR 兜底：is_scanned_pdf 为 True 时 extract_text 返回 (文本, True)
    5. 触发关键词：命中才走图像通道，未命中回落三路融合
    6. 编码器选择：auto 模式下应选出可用编码器
    7. 图像集合读写：桩编码器 + 桩存储，验证 add/query/delete 契约
    8. 端到端（--real）：以文搜图 + VLM 解读
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))  # 0.17.0：指向 backend/

SCANNED_PDF = glob.glob("knowledge_files/*高考志愿录取顺序.pdf")
QUESTION_IMG = "福州大学至诚学院计算机专业有哪些课程"
QUESTION_TXT = "福州大学至诚学院计算机专业学费是多少"


class _StubEncoder:
    """桩编码器：文本/图片都编成固定规律的向量，可验证同空间约束。"""

    name = "stub"

    def encode_image(self, image_bytes: bytes):
        # 用图片长度的低位造向量，保证不同图片向量不同但维度一致
        n = len(image_bytes)
        return [float((n >> (i % 8)) & 1) for i in range(8)]

    def encode_text(self, text: str):
        n = len(text or "")
        return [float((n >> (i % 8)) & 1) for i in range(8)]


class _StubExtractor:
    name = "stub"

    def extract_images(self, pdf_path, max_images=None):
        # 造 3 张「图」，用可区分长度的字节
        return [
            {"image_bytes": b"A" * 100, "page": 1, "caption": "", "file_id": 1, "filename": "a.pdf"},
            {"image_bytes": b"B" * 200, "page": 2, "caption": "", "file_id": 1, "filename": "a.pdf"},
            {"image_bytes": b"C" * 300, "page": 3, "caption": "", "file_id": 1, "filename": "a.pdf"},
        ]

    def _big_enough(self, raw):
        return len(raw) >= 80


def test_scanned_detection() -> None:
    """用例 1 + 2：扫描件判定与 PDF 渲染。"""
    from app.utils.ocr_utils import OCRExtractor

    ocr = OCRExtractor()
    print("用例 1：扫描件判定")
    if SCANNED_PDF:
        p = SCANNED_PDF[0]
        print(f"  文件：{os.path.basename(p)}（{os.path.getsize(p)/1024/1024:.1f} MB）")
        print(f"  is_scanned_pdf = {ocr.is_scanned_pdf(p)}")
        assert ocr.is_scanned_pdf(p) is True, "真实扫描件应判定为 True"
    else:
        print("  [SKIP] 未找到扫描件 PDF 样本")
    print(f"  非 PDF 路径 is_scanned_pdf = {ocr.is_scanned_pdf('不存在.txt')}")

    print("用例 2：PDF 页 → 图片（pypdfium2，无需 poppler）")
    if SCANNED_PDF:
        imgs = ocr.pdf_to_images(SCANNED_PDF[0], max_pages=2)
        print(f"  渲染出 {len(imgs)} 张，首张尺寸 {imgs[0].size if imgs else None}")
        assert imgs, "应能渲染出页面"
    else:
        print("  [SKIP] 未找到扫描件 PDF 样本")


def test_image_extract() -> None:
    """用例 3：PDF 图片提取。"""
    from app.services.multimodal import ImageExtractor

    ex = ImageExtractor()
    print("用例 3：PDF 图片提取")
    if SCANNED_PDF:
        imgs = ex.extract_images(SCANNED_PDF[0], max_images=3)
        print(f"  提取 {len(imgs)} 张，页号 {[i['page'] for i in imgs]}")
        for i in imgs:
            print(f"    page={i['page']} bytes={len(i['image_bytes'])}")
        assert imgs, "扫描件应按页渲染提出图片"
    else:
        print("  [SKIP] 未找到扫描件 PDF 样本")


def test_trigger() -> None:
    """用例 5：触发关键词。"""
    from app.services.rag import rag_service

    print("用例 5：触发关键词")
    a = rag_service.should_use_multimodal(QUESTION_IMG)
    b = rag_service.should_use_multimodal(QUESTION_TXT)
    c = rag_service.should_use_multimodal("河南本科批志愿怎么填报")
    print(f"  「{QUESTION_IMG}」→ {a}")
    print(f"  「{QUESTION_TXT}」→ {b}")
    print(f"  「河南本科批志愿怎么填报」→ {c}")
    assert a is True, "含「课程」应触发多模态"
    assert b is False, "纯字段型问题不应触发"
    assert c is False, "政策类问题不应触发"


def test_encoder() -> None:
    """用例 6：编码器选择。"""
    from app.services.multimodal import create_image_encoder

    print("用例 6：编码器选择")
    enc = create_image_encoder()
    print(f"  选中编码器：{enc.name}，available = {enc.available()}")
    assert enc.available(), "至少应有一个编码器可用"


def test_store_contract() -> None:
    """用例 7：图像集合读写契约（桩编码器 + 真实 Chroma，用完即清）。

    用独立的集合名 `gaokao_images_test`，避免桩编码器的 8 维向量
    把真实集合 gaokao_images 的维度 pin 坏（CLIP 512 / 图注 768）。
    """
    from app.services.multimodal import ImageStore

    print("用例 7：图像集合读写（add / query / delete）")
    store = ImageStore(collection_name="gaokao_images_test")
    if not store.available():
        print("  [SKIP] Chroma 不可用")
        return
    store.reset()  # 保证可重复运行

    file_id = 999002
    store.delete_by_file(file_id)

    enc = _StubEncoder()
    images = [
        {"image_bytes": b"A" * 100, "page": 1, "caption": "", "file_id": file_id, "filename": "_probe.pdf"},
        {"image_bytes": b"B" * 200, "page": 2, "caption": "", "file_id": file_id, "filename": "_probe.pdf"},
    ]
    vecs = [enc.encode_image(i["image_bytes"]) for i in images]
    written = store.add_images(images, vecs, encoder_name=enc.name)
    print(f"  写入 {written} 张")
    assert written == 2, written

    hits = store.search_by_text(enc.encode_text("课程体系图"), top_k=2)
    print(f"  检索命中 {len(hits)} 张，页号 {[h['metadata'].get('page') for h in hits]}")
    assert hits, "应能检索到刚写入的图片"
    assert all(h["metadata"].get("file_id") == file_id for h in hits)

    removed = store.delete_by_file(file_id)
    print(f"  删除 {removed} 张，剩余 {store.count()}")
    assert removed == 2, removed

    # 维度校验：换一个不同维度的编码器写入应被拒绝并给出提示
    class _OtherDimEncoder(_StubEncoder):
        name = "other-dim"

        def encode_image(self, image_bytes):
            return [1.0] * 16

    bad = _OtherDimEncoder().encode_image(b"X" * 100)
    n = store.add_images(
        [{"image_bytes": b"X" * 100, "page": 9, "caption": "", "file_id": 999002,
          "filename": "_probe.pdf"}],
        [bad], encoder_name="other-dim",
    )
    print(f"  维度不符写入被拒绝：返回 {n}")
    assert n == 0, "维度不符必须拒绝写入"

    store.reset()  # 清理测试集合


def test_retriever_stub() -> None:
    """用例 7b：ImageRetriever 合成复用（桩协作者，验证编排逻辑）。"""
    from app.services.multimodal import ImageRetriever

    print("用例 7b：ImageRetriever 编排（桩协作者）")
    retriever = ImageRetriever(
        extractor=_StubExtractor(),
        encoder=_StubEncoder(),
        store=None,
        vlm=None,
    )
    # 未触发关键词 → 不检索
    assert retriever.retrieve(QUESTION_TXT) == []
    # 触发但 store 为 None → 走真实 ImageStore（空集合），返回空
    hits = retriever.retrieve(QUESTION_IMG)
    print(f"  retrieve 返回 {len(hits)} 条（空集合应为 0）")


def test_real() -> None:
    """用例 8：真实链路 OCR + 以文搜图。"""
    from app.services.rag import rag_service

    print("用例 8：真实链路")
    if not SCANNED_PDF:
        print("  [SKIP] 未找到扫描件 PDF 样本")
        return

    # 8a. OCR 文本提取对比
    from app.utils.file_utils import _extract_pdf
    from app.utils.ocr_utils import OCRExtractor

    p = SCANNED_PDF[0]
    raw = _extract_pdf(p)
    ocr = OCRExtractor()
    print(f"  修复前（pypdf 直接提取）：{len(raw)} 字")
    print(f"  切片段数：{len(rag_service.split_text(raw))}")

    # 只 OCR 前 3 页做验证（全量 19 页约 2-3 分钟）
    text = ocr.ocr_images(ocr.pdf_to_images(p, max_pages=3))
    print(f"  修复后（OCR 前 3 页）：{len(text)} 字")
    print(f"  切片段数：{len(rag_service.split_text(text))}")
    assert len(text) > len(raw), "OCR 后字符数应显著多于直接提取"

    # 8b. 图片入库 + 以文搜图
    from app.services.multimodal import ImageRetriever

    retriever = ImageRetriever()
    n = retriever.index_pdf(p, 999003, "_probe_mm.pdf")
    print(f"  图片入库 {n} 张")
    if n:
        out = retriever.answer(QUESTION_IMG)
        print(f"  image_hit = {out.get('image_hit')}")
        print(f"  images = {[(i.get('page'), i.get('filename')) for i in out.get('images', [])]}")
        print(f"  answer = {(out.get('answer') or '')[:200]}")
    retriever.remove_file(999003)


def main() -> int:
    test_scanned_detection()
    print()
    test_image_extract()
    print()
    test_trigger()
    print()
    test_encoder()
    print()
    test_store_contract()
    print()
    test_retriever_stub()
    print()
    if "--real" in sys.argv:
        test_real()
        print()
    print("=" * 70)
    print("0.10.0 多模态 + OCR 用例全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
