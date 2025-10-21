from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Tuple

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

try:
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover
    pytesseract = None


def _preprocess(image_bytes: bytes):
    if not Image:
        return None
    image = Image.open(BytesIO(image_bytes))
    image = image.convert("L")
    if cv2 and np:
        arr = np.array(image)
        
        # 多种预处理方法
        methods = []
        
        # 方法1: OTSU阈值
        _, thresh1 = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        methods.append(thresh1)
        
        # 方法2: 自适应阈值
        thresh2 = cv2.adaptiveThreshold(arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        methods.append(thresh2)
        
        # 方法3: 固定阈值
        _, thresh3 = cv2.threshold(arr, 128, 255, cv2.THRESH_BINARY)
        methods.append(thresh3)
        
        # 方法4: 形态学操作
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        opened = cv2.morphologyEx(thresh1, cv2.MORPH_OPEN, kernel)
        methods.append(opened)
        
        # 方法5: 高斯模糊 + OTSU
        blurred = cv2.GaussianBlur(arr, (3, 3), 0)
        _, thresh5 = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        methods.append(thresh5)
        
        # 选择对比度最高的方法
        best_method = max(methods, key=lambda x: np.std(x))
        image = Image.fromarray(best_method)
    else:
        # 多种阈值尝试
        thresholds = [128, 140, 160, 180]
        best_image = None
        best_contrast = 0
        
        for thresh in thresholds:
            test_image = image.point(lambda x: 0 if x < thresh else 255, "1")
            # 简单的对比度计算
            data = list(test_image.getdata())
            if len(data) > 1:
                contrast = sum(abs(p1 - p2) for p1, p2 in zip(data[:-1], data[1:]))
            else:
                contrast = 0
            if contrast > best_contrast:
                best_contrast = contrast
                best_image = test_image
        
        image = best_image or image.point(lambda x: 0 if x < 140 else 255, "1")
    
    return image


def solve_captcha(image_bytes: bytes) -> Tuple[str, float]:
    if not pytesseract or not Image:
        return "", 0.0
    image = _preprocess(image_bytes)
    if image is None:
        return "", 0.0
    
    # 尝试多种OCR配置，选择最佳结果
    configs = [
        # 单行文本识别
        "--psm 7 --oem 1 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "--psm 8 --oem 1 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "--psm 13 --oem 1 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        # 单字符识别
        "--psm 10 --oem 1 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "--psm 10 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        # 单行文本，不限制字符
        "--psm 7 --oem 1",
        "--psm 8 --oem 1",
        "--psm 13 --oem 1",
        # 单字符，不限制字符
        "--psm 10 --oem 1",
        "--psm 10 --oem 3",
    ]
    
    best_text = ""
    best_confidence = 0.0
    results = []
    
    for config in configs:
        try:
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config=config)
            text = data.get("text") or []
            text_str = "".join(text).strip().replace(" ", "")
            confidences = [int(c) for c in data.get("conf", []) if c not in (-1, "-1")]
            confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
            
            # 收集所有结果
            if text_str and len(text_str) >= 3:  # 至少3个字符
                results.append((text_str, confidence, config))
                
        except Exception:
            continue
    
    # 智能选择最佳结果
    if results:
        # 按置信度排序
        results.sort(key=lambda x: x[1], reverse=True)
        
        # 优先选择长度在4-6个字符的结果
        for text_str, confidence, config in results:
            if 4 <= len(text_str) <= 6:
                best_text = text_str
                best_confidence = confidence
                break
        
        # 如果没有合适长度的结果，选择置信度最高的
        if not best_text:
            best_text, best_confidence, _ = results[0]
    
    # 如果所有配置都失败，使用默认配置
    if not best_text:
        config = "--psm 7 --oem 1 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config=config)
        text = data.get("text") or []
        best_text = "".join(text).strip().replace(" ", "")
        confidences = [int(c) for c in data.get("conf", []) if c not in (-1, "-1")]
        best_confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    
    # 字符相似度检查和修正
    if best_text:
        best_text = _correct_similar_chars(best_text)
    
    return best_text, best_confidence


def _correct_similar_chars(text: str) -> str:
    """修正容易混淆的字符"""
    corrections = {
        '0': 'O',  # 数字0 -> 字母O
        '1': 'I',  # 数字1 -> 字母I
        '5': 'S',  # 数字5 -> 字母S
        '6': 'G',  # 数字6 -> 字母G
        '8': 'B',  # 数字8 -> 字母B
    }
    
    # 如果文本全是数字，尝试转换为字母
    if text.isdigit() and len(text) >= 4:
        corrected = ""
        for char in text:
            corrected += corrections.get(char, char)
        return corrected
    
    return text


async def solve_captcha_async(image_bytes: bytes) -> Tuple[str, float]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, solve_captcha, image_bytes)
