"""
KNN 기반 수어 분류기 서비스
- 훈련된 knn_model.pkl 을 로드하여 실시간 예측 수행
- 신뢰도(confidence) 임계값 이상인 경우만 결과 반환
"""
import math
import joblib
import numpy as np
from pathlib import Path
from typing import Optional

MODEL_PATH = Path("api/data/ksl_training/knn_model.pkl")
CONFIDENCE_THRESHOLD = 0.60  # 60% 이하 신뢰도는 '미인식'으로 처리

_model = None  # 싱글톤 캐시


def _load_model():
    global _model
    if _model is None and MODEL_PATH.exists():
        _model = joblib.load(MODEL_PATH)
        print(f"[KNN] 모델 로드 완료 — 인식 단어: {list(_model.classes_)}")
    return _model


def extract_features(landmarks: list) -> Optional[list]:
    """
    21개 MediaPipe 랜드마크 dict 리스트 → 16차원 특징 벡터
    """
    if not landmarks or len(landmarks) < 21:
        return None

    wrist = landmarks[0]
    pts = [(lm["x"] - wrist["x"], lm["y"] - wrist["y"],
            lm.get("z", 0) - wrist.get("z", 0)) for lm in landmarks]

    mid_tip = pts[12]
    scale = math.hypot(mid_tip[0], mid_tip[1])
    if scale < 1e-6:
        return None
    pts = [(p[0]/scale, p[1]/scale, p[2]/scale) for p in pts]

    def angle(a, b, c):
        ab = (b[0]-a[0], b[1]-a[1])
        cb = (b[0]-c[0], b[1]-c[1])
        dot = ab[0]*cb[0] + ab[1]*cb[1]
        m = math.hypot(*ab) * math.hypot(*cb)
        return math.acos(max(-1.0, min(1.0, dot/m))) if m > 1e-9 else 0.0

    fingers = [
        [1, 2, 3, 4],
        [5, 6, 7, 8],
        [9, 10, 11, 12],
        [13, 14, 15, 16],
        [17, 18, 19, 20],
    ]

    features = []
    for f in fingers:
        features.append(angle(pts[0],    pts[f[0]], pts[f[1]]))
        features.append(angle(pts[f[0]], pts[f[1]], pts[f[2]]))
        features.append(angle(pts[f[1]], pts[f[2]], pts[f[3]]))
    features.append(scale)

    return features


def predict(landmarks: list) -> tuple[Optional[str], float]:
    """
    랜드마크 → (단어, 신뢰도) 반환.
    모델이 없거나 신뢰도 부족 시 (None, 0.0) 반환.
    """
    model = _load_model()
    if model is None:
        return None, 0.0

    features = extract_features(landmarks)
    if features is None:
        return None, 0.0

    proba = model.predict_proba([features])[0]
    idx = int(np.argmax(proba))
    confidence = float(proba[idx])
    label = model.classes_[idx]

    if confidence < CONFIDENCE_THRESHOLD:
        return None, confidence

    return label, confidence


def is_model_ready() -> bool:
    return _load_model() is not None
