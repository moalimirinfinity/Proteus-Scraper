from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

from core.config import settings

logger = logging.getLogger(__name__)

_OCR_PATTERNS = [
    r"captcha",
    r"verify you are human",
    r"are you human",
    r"robot check",
    r"access denied",
    r"unusual traffic",
    r"blocked",
    r"security check",
]


@dataclass(frozen=True)
class VisionAnalysis:
    ocr_text: str | None = None
    ocr_reason: str | None = None
    yolo_labels: list[str] = field(default_factory=list)
    yolo_reason: str | None = None


def analyze_screenshot(image_bytes: bytes | None) -> VisionAnalysis:
    if not image_bytes:
        return VisionAnalysis()

    ocr_text = None
    ocr_reason = None
    yolo_labels: list[str] = []
    yolo_reason = None

    if settings.vision_ocr_enabled:
        ocr_text = _extract_text(image_bytes)
        if ocr_text:
            ocr_reason = detect_ocr_signal(ocr_text)

    if settings.vision_yolo_enabled:
        labels = _detect_yolo_labels(image_bytes)
        if labels:
            yolo_labels = labels
            yolo_reason = f"vision_yolo:{','.join(labels)}"

    return VisionAnalysis(
        ocr_text=ocr_text,
        ocr_reason=ocr_reason,
        yolo_labels=yolo_labels,
        yolo_reason=yolo_reason,
    )


def detect_ocr_signal(text: str) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for pattern in _OCR_PATTERNS:
        if re.search(pattern, lowered):
            return "vision_ocr_block"
    return None


def _extract_text(image_bytes: bytes) -> str | None:
    provider = (settings.vision_ocr_provider or "tesseract").strip().lower()
    if provider in {"tesseract", "pytesseract"}:
        return _extract_text_tesseract(image_bytes, settings.vision_ocr_language)
    if provider in {"paddle", "paddleocr"}:
        return _extract_text_paddle(image_bytes)
    logger.warning("ocr_provider_unrecognized: %s", provider)
    return None


def _extract_text_tesseract(image_bytes: bytes, language: str) -> str | None:
    try:
        from PIL import Image
    except Exception:
        logger.warning("ocr_pillow_unavailable")
        return None
    try:
        import pytesseract
    except Exception:
        logger.warning("ocr_tesseract_unavailable")
        return None
    try:
        image = Image.open(io.BytesIO(image_bytes))
    except Exception:
        logger.exception("ocr_image_decode_failed")
        return None
    try:
        text = pytesseract.image_to_string(image, lang=language or "eng")
    except Exception:
        logger.exception("ocr_tesseract_failed")
        return None
    return text.strip() if text else None


def _extract_text_paddle(image_bytes: bytes) -> str | None:
    try:
        from paddleocr import PaddleOCR
    except Exception:
        logger.warning("ocr_paddle_unavailable")
        return None
    try:
        import numpy as np
    except Exception:
        logger.warning("ocr_numpy_unavailable")
        return None
    try:
        from PIL import Image
    except Exception:
        logger.warning("ocr_pillow_unavailable")
        return None
    try:
        ocr = _paddle_instance()
    except Exception:
        logger.exception("ocr_paddle_init_failed")
        return None
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        result = ocr.ocr(np.array(image), cls=True)
    except Exception:
        logger.exception("ocr_paddle_failed")
        return None
    if not result:
        return None
    chunks: list[str] = []
    for page in result:
        for line in page or []:
            if len(line) >= 2 and isinstance(line[1], (list, tuple)):
                text = line[1][0]
            else:
                text = line[1] if len(line) > 1 else None
            if text:
                chunks.append(str(text))
    combined = " ".join(chunks)
    return combined.strip() if combined else None


@lru_cache(maxsize=1)
def _paddle_instance():
    from paddleocr import PaddleOCR

    return PaddleOCR(use_angle_cls=True, lang="en")


def _detect_yolo_labels(image_bytes: bytes) -> list[str]:
    classes = _parse_yolo_classes(settings.vision_yolo_classes)
    if not classes:
        return []
    try:
        from PIL import Image
    except Exception:
        logger.warning("yolo_pillow_unavailable")
        return []
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        logger.exception("yolo_image_decode_failed")
        return []
    try:
        model = _yolo_model()
    except Exception:
        logger.exception("yolo_model_load_failed")
        return []
    try:
        results = model.predict(image, conf=settings.vision_yolo_confidence, verbose=False)
    except Exception:
        logger.exception("yolo_inference_failed")
        return []
    if not results:
        return []

    labels: list[str] = []
    class_names = model.names if hasattr(model, "names") else {}
    targets = set(classes)
    target_ids = {int(item) for item in classes if item.isdigit()}
    for result in results:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
        for cls in boxes.cls.tolist() if hasattr(boxes, "cls") else []:
            cls_id = int(cls)
            label = str(class_names.get(cls_id, cls_id))
            if cls_id in target_ids or label.lower() in targets:
                if label not in labels:
                    labels.append(label)
    return labels


@lru_cache(maxsize=1)
def _yolo_model():
    from ultralytics import YOLO

    return YOLO(settings.vision_yolo_model or "yolov8n.pt")


def _parse_yolo_classes(value: str | None) -> list[str]:
    if not value:
        return []
    return [entry.strip().lower() for entry in value.split(",") if entry.strip()]
