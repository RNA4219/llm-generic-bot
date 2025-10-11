from __future__ import annotations
from typing import Deque, Tuple
from collections import deque
import math, re

def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s[:512]

def similarity(a: str, b: str) -> float:
    # 超軽量: 文字 n-gram Jaccard 近似（高速・依存なし）
    def ngrams(t): return set([t[i:i+3] for i in range(max(1, len(t)-2))])
    A, B = ngrams(_norm(a)), ngrams(_norm(b))
    if not A or not B: return 0.0
    return len(A & B) / len(A | B)

class NearDuplicateFilter:
    def __init__(self, k: int = 20, threshold: float = 0.93):
        self.k = k
        self.th = threshold
        self.buf: Deque[str] = deque(maxlen=k)

    def permit(self, text: str) -> bool:
        for prev in self.buf:
            if similarity(prev, text) >= self.th:
                return False
        self.buf.append(text)
        return True
