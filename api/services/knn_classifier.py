"""
KNN 기반 수어 분류기 서비스
- 훈련된 knn_model.pkl 을 로드하여 실시간 예측 수행
- 신뢰도(confidence) 임계값 이상인 경우만 결과 반환
"""

import math
import joblib
import threading
import numpy as np
from pathlib import Path
from typing import Optional

MODEL_PATH = Path("api/data/ksl_training/knn_model.pkl")
DIALOGUE_MODEL_PATH = Path("api/data/ksl_training/knn_model_dialogue.pkl")
CONFIDENCE_THRESHOLD = 0.35  # 조금 더 관대하게 허용하여 실제 손동작 인식 빈도 향상

_model = None  # 싱글톤 캐시
current_model_type = "main"  # 기본 모델타입 ('main' 또는 'dialogue')
_model_lock = threading.Lock()  # 모델 로드/교체 경합 방지


def set_model_type(model_type: str) -> str:
    """실시간으로 사용할 모델 종류를 설정합니다 ('main' 또는 'dialogue')"""
    global current_model_type, _model
    if model_type not in ["main", "dialogue"]:
        raise ValueError("Invalid model type. Choose 'main' or 'dialogue'.")
    current_model_type = model_type
    _model = None  # 캐시 무효화
    reload_model()
    return current_model_type


def get_model_type() -> str:
    """현재 로드된 모델 타입 조회"""
    return current_model_type


def reload_model():
    """모델을 강제로 다시 로드하여 메모리를 갱신합니다 (핫-리로딩)"""
    global _model
    # 학습(워커 스레드)과 모델 교체가 동시에 joblib.load 를 호출하는 경합을 방지
    with _model_lock:
        target_path = MODEL_PATH if current_model_type == "main" else DIALOGUE_MODEL_PATH
        if target_path.exists():
            _model = joblib.load(target_path)
            print(
                f"[KNN] 모델 리로드 완료 ({current_model_type}) - 인식 단어: {list(_model.classes_)}"
            )
        else:
            _model = None
    return _model


def _load_model():
    global _model
    target_path = MODEL_PATH if current_model_type == "main" else DIALOGUE_MODEL_PATH
    if _model is None and target_path.exists():
        return reload_model()
    return _model


from api.core.ml_utils import (
    extract_ksl_features,
    snapshot_prev_state,
    restore_prev_state,
)


# 포즈의 좌/우 짝 — 양손 스왑 시 동시에 바뀌어야 함 (어깨·팔꿈치·손목·엉덩이)
_POSE_LR_PAIRS = [
    ("left_shoulder", "right_shoulder"),
    ("left_elbow", "right_elbow"),
    ("left_wrist", "right_wrist"),
    ("left_hip", "right_hip"),
]


def _swap_pose_lr(pose_lms):
    """포즈 데이터의 좌/우 짝을 교환해 새 dict 반환. 원본 보존."""
    if not pose_lms:
        return pose_lms
    inner = pose_lms.get("landmarks") if isinstance(pose_lms, dict) else None
    if inner is None:
        return pose_lms
    new_inner = dict(inner)
    for a, b in _POSE_LR_PAIRS:
        if a in inner or b in inner:
            new_inner[a], new_inner[b] = inner.get(b), inner.get(a)
            # 비어있는 값 정리
            if new_inner[a] is None: new_inner.pop(a, None)
            if new_inner[b] is None: new_inner.pop(b, None)
    return {**pose_lms, "landmarks": new_inner}


# 필수적으로 양손을 모두 사용해야 하는 수어 단어 정의
TWO_HANDED_SIGNS = {"친구", "집", "감사", "오늘", "안녕"}

# 필수적으로 한 손만 사용해야 하는 수어 단어 정의
ONE_HANDED_SIGNS = {
    "나",
    "너",
    "이름",
    "내일",
    "오다",
    "알다",
    "맛있다",
    "좋다",
    "잘하다,좋다",
    "가다",
}


def predict(
    right_lms: Optional[list], left_lms: Optional[list], pose_lms: Optional[dict] = None
) -> tuple[Optional[str], float]:
    """
    양손 랜드마크 + 팔 관절 → (단어, 신뢰도) 반환.
    양손 스왑(Ambidextrous) 폴백을 적용하여 좌우 반전 및 왼손잡이 대응.
    """
    model = _load_model()
    if model is None:
        return None, 0.0

    # 실시간 감지된 유효한 손 개수 계산
    detected_hands = 0
    if right_lms and len(right_lms) >= 21:
        detected_hands += 1
    if left_lms and len(left_lms) >= 21:
        detected_hands += 1

    # 1. 정방향 시도 (오른손=R, 왼손=L)
    feats_normal = extract_ksl_features(right_lms, left_lms, pose_lms)
    if feats_normal is None:
        return None, 0.0

    proba_normal = model.predict_proba([feats_normal])[0]
    idx_n = int(np.argmax(proba_normal))
    conf_normal = float(proba_normal[idx_n])
    label_normal = model.classes_[idx_n]

    # 정방향 패스가 갱신한 속도 계산용 상태(_prev_state)를 보존해 둔다.
    # 아래 역방향(스왑) 시도는 보조 추론이므로 이 상태를 오염시키면 안 된다.
    state_after_normal = snapshot_prev_state()

    # 2. 역방향 시도 (오른손=L, 왼손=R) — 좌우 반전/스왑 대응 (왼손잡이 / 거울)
    #    손 좌표뿐 아니라 포즈의 좌/우 짝(어깨·팔꿈치·손목·엉덩이)도 동시에 스왑해야
    #    상대 위치 특성(rel_pos)과 팔 각도(arm_feats)가 올바르게 계산된다.
    pose_lms_swapped = _swap_pose_lr(pose_lms)
    feats_swap = extract_ksl_features(left_lms, right_lms, pose_lms_swapped)
    conf_swap = 0.0
    label_swap = None
    if feats_swap is not None:
        proba_swap = model.predict_proba([feats_swap])[0]
        idx_s = int(np.argmax(proba_swap))
        conf_swap = float(proba_swap[idx_s])
        label_swap = model.classes_[idx_s]

    # 보조 추론이 끝났으니, 다음 프레임의 속도 계산을 위해
    # 정방향 기준 상태로 _prev_state를 복원한다.
    restore_prev_state(state_after_normal)

    # 3. 더 높은 신뢰도 선택
    if conf_normal >= conf_swap:
        final_label, final_conf = label_normal, conf_normal
    else:
        final_label, final_conf = label_swap, conf_swap

    # [양손 수어 가드 - 손 개수 + 근접도 이중 검증]
    if final_label in TWO_HANDED_SIGNS:
        # 1) 한 손만 감지되면 즉시 차단
        if detected_hands < 2:
            print(
                f"[KNN Guard] '{final_label}' 차단: 양손 수어인데 손 {detected_hands}개만 감지"
            )
            return None, 0.0
        # 2) 두 손 다 보이더라도, 양손이 실제로 가까이서 상호작용하는지 검증
        #    (쉬고 있는 손이 허리/책상 아래에서 잡히는 경우를 걸러냄)
        if right_lms and left_lms and len(right_lms) >= 1 and len(left_lms) >= 1:
            r_wrist = right_lms[0]
            l_wrist = left_lms[0]
            y_dist = abs(r_wrist["y"] - l_wrist["y"])
            x_dist = abs(r_wrist["x"] - l_wrist["x"])
            if y_dist > 0.18 or x_dist > 0.35:
                print(
                    f"[KNN Proximity Guard] '{final_label}' 차단: 양손 거리 너무 멀음 (y={y_dist:.3f}, x={x_dist:.3f})"
                )
                return None, 0.0

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
