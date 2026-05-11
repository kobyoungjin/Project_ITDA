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
CONFIDENCE_THRESHOLD = 0.55  # [개선안 3] 신뢰도 임계값 상향 (불확실한 예측 차단)

_model = None  # 싱글톤 캐시


def reload_model():
    """모델을 강제로 다시 로드하여 메모리를 갱신합니다 (핫-리로딩)"""
    global _model
    if MODEL_PATH.exists():
        _model = joblib.load(MODEL_PATH)
        print(f"[KNN] 모델 리로드 완료 (실시간 갱신) — 인식 단어: {list(_model.classes_)}")
    else:
        _model = None
    return _model

def _load_model():
    global _model
    if _model is None and MODEL_PATH.exists():
        return reload_model()
    return _model


from api.core.ml_utils import extract_ksl_features

def predict(right_lms: Optional[list], left_lms: Optional[list]) -> tuple[Optional[str], float]:
    """
    양손 랜드마크 → (단어, 신뢰도) 반환.
    양손 스왑(Ambidextrous) 폴백을 적용하여 좌우 반전 및 왼손잡이 대응.
    """
    model = _load_model()
    if model is None:
        return None, 0.0

    # 1. 정방향 시도 (오른손=R, 왼손=L)
    feats_normal = extract_ksl_features(right_lms, left_lms)
    if feats_normal is None:
        return None, 0.0
    
    proba_normal = model.predict_proba([feats_normal])[0]
    idx_n = int(np.argmax(proba_normal))
    conf_normal = float(proba_normal[idx_n])
    label_normal = model.classes_[idx_n]

    # 2. 역방향 시도 (오른손=L, 왼손=R) - 좌우 반전/스왑 대응
    feats_swap = extract_ksl_features(left_lms, right_lms)
    conf_swap = 0.0
    label_swap = None
    if feats_swap:
        proba_swap = model.predict_proba([feats_swap])[0]
        idx_s = int(np.argmax(proba_swap))
        conf_swap = float(proba_swap[idx_s])
        label_swap = model.classes_[idx_s]

    # 3. 더 높은 신뢰도 선택
    if conf_normal >= conf_swap:
        final_label, final_conf = label_normal, conf_normal
    else:
        final_label, final_conf = label_swap, conf_swap

    if final_conf < CONFIDENCE_THRESHOLD:
        return None, final_conf

    return final_label, final_conf


def is_model_ready() -> bool:
    return _load_model() is not None


def get_labels() -> list[str]:
    """현재 모델이 학습한 단어 목록 반환"""
    model = _load_model()
    if model is not None:
        return list(model.classes_)
    return []
