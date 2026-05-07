"""
수어 학습 데이터 수집 API
- POST /api/collect/start   : 수집 시작 (단어 레이블 지정)
- POST /api/collect/stop    : 수집 중지
- POST /api/collect/sample  : 프론트에서 랜드마크 1프레임 저장
- GET  /api/collect/status  : 현재 수집 상태 조회
- POST /api/collect/train   : 수집된 데이터로 KNN 훈련
"""
import os
import csv
import math
import time
import joblib
import numpy as np
from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()

# ── 저장 경로 ────────────────────────────────────────────────
DATA_DIR = Path("api/data/ksl_training")
DATA_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = DATA_DIR / "ksl_dataset.csv"
MODEL_PATH = DATA_DIR / "knn_model.pkl"

# ── 수집 상태 (인메모리) ─────────────────────────────────────
_collect_state = {
    "active": False,
    "label": "",
    "count": 0,
    "started_at": 0.0,
}

# ── Pydantic 모델 ─────────────────────────────────────────────
class StartRequest(BaseModel):
    label: str  # 예: "안녕하세요"

class SampleRequest(BaseModel):
    # MediaPipe 21개 랜드마크 [{"x":..,"y":..,"z":..}, ...]
    landmarks: List[dict]
    handedness: Optional[str] = "Right"

class TrainRequest(BaseModel):
    n_neighbors: int = 5


# ── 특징 추출 함수 ────────────────────────────────────────────
def _extract_features(landmarks: List[dict]) -> Optional[List[float]]:
    """
    21개 MediaPipe 랜드마크 → 손목 기준 정규화 후 각도 15개 + 거리 1개 추출
    총 16차원 특징 벡터 반환
    """
    if not landmarks or len(landmarks) < 21:
        return None

    # 손목(0번)을 원점으로 정규화
    wrist = landmarks[0]
    pts = [(lm["x"] - wrist["x"], lm["y"] - wrist["y"], lm.get("z", 0) - wrist.get("z", 0))
           for lm in landmarks]

    # 중지 끝(12번)까지 거리로 스케일 정규화
    mid_tip = pts[12]
    scale = math.hypot(mid_tip[0], mid_tip[1])
    if scale < 1e-6:
        return None
    pts = [(p[0]/scale, p[1]/scale, p[2]/scale) for p in pts]

    def angle(a, b, c):
        """세 점 사이의 각도(라디안) 계산"""
        ab = (b[0]-a[0], b[1]-a[1])
        cb = (b[0]-c[0], b[1]-c[1])
        dot = ab[0]*cb[0] + ab[1]*cb[1]
        mag_ab = math.hypot(*ab)
        mag_cb = math.hypot(*cb)
        if mag_ab * mag_cb < 1e-9:
            return 0.0
        return math.acos(max(-1.0, min(1.0, dot / (mag_ab * mag_cb))))

    # 손가락 마디 인덱스: [MCP, PIP, DIP, TIP]
    fingers = [
        [1, 2, 3, 4],    # 엄지
        [5, 6, 7, 8],    # 검지
        [9, 10, 11, 12], # 중지
        [13, 14, 15, 16],# 약지
        [17, 18, 19, 20],# 소지
    ]

    features = []
    for f in fingers:
        # 각 손가락의 3개 관절 각도
        features.append(angle(pts[0], pts[f[0]], pts[f[1]]))   # 손목-MCP-PIP
        features.append(angle(pts[f[0]], pts[f[1]], pts[f[2]])) # MCP-PIP-DIP
        features.append(angle(pts[f[1]], pts[f[2]], pts[f[3]])) # PIP-DIP-TIP

    # 스케일(중지 끝 거리) 자체도 특징으로
    features.append(scale)

    return features  # 16차원


# ── API 엔드포인트 ────────────────────────────────────────────
@router.post("/start")
def start_collection(req: StartRequest):
    """수집 모드 시작 (단어 레이블 지정)"""
    _collect_state["active"] = True
    _collect_state["label"] = req.label.strip()
    _collect_state["count"] = 0
    _collect_state["started_at"] = time.time()
    return {"ok": True, "label": _collect_state["label"], "message": f"'{req.label}' 수집 시작!"}


@router.post("/stop")
def stop_collection():
    """수집 모드 중지"""
    count = _collect_state["count"]
    label = _collect_state["label"]
    _collect_state["active"] = False
    return {"ok": True, "label": label, "count": count, "message": f"{count}개 샘플 저장 완료"}


@router.get("/status")
def get_status():
    """현재 수집 상태 반환"""
    return {
        "active": _collect_state["active"],
        "label": _collect_state["label"],
        "count": _collect_state["count"],
        "csv_exists": CSV_PATH.exists(),
        "model_exists": MODEL_PATH.exists(),
    }


@router.post("/sample")
def add_sample(req: SampleRequest):
    """
    프론트엔드에서 1프레임의 랜드마크 데이터를 전송하면 CSV에 저장
    """
    if not _collect_state["active"]:
        return {"ok": False, "message": "수집 모드가 비활성화 상태입니다. /start 먼저 호출하세요."}

    features = _extract_features(req.landmarks)
    if features is None:
        return {"ok": False, "message": "랜드마크 데이터 불충분 (21개 필요)"}

    label = _collect_state["label"]
    is_new = not CSV_PATH.exists()

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            header = [f"f{i}" for i in range(len(features))] + ["label"]
            writer.writerow(header)
        writer.writerow(features + [label])

    _collect_state["count"] += 1
    return {"ok": True, "count": _collect_state["count"], "label": label}


@router.post("/train")
def train_knn(req: TrainRequest):
    """수집된 CSV 데이터로 KNN 모델 훈련"""
    if not CSV_PATH.exists():
        return {"ok": False, "message": "학습 데이터가 없습니다. 먼저 샘플을 수집하세요."}

    import pandas as pd
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.model_selection import cross_val_score

    df = pd.read_csv(CSV_PATH)
    if len(df) < 10:
        return {"ok": False, "message": f"샘플 수 부족 ({len(df)}개). 최소 10개 이상 필요합니다."}

    X = df.drop("label", axis=1).values
    y = df["label"].values
    labels = sorted(set(y))

    model = KNeighborsClassifier(n_neighbors=req.n_neighbors, metric="euclidean", weights="distance")
    
    # 교차 검증으로 정확도 측정
    if len(df) >= 20:
        scores = cross_val_score(model, X, y, cv=min(5, len(labels)), scoring="accuracy")
        accuracy = float(scores.mean())
    else:
        accuracy = None

    model.fit(X, y)
    joblib.dump(model, MODEL_PATH)

    return {
        "ok": True,
        "samples": int(len(df)),
        "labels": labels,
        "label_count": len(labels),
        "accuracy": round(accuracy * 100, 1) if accuracy else "샘플 부족으로 측정 불가",
        "model_path": str(MODEL_PATH),
        "message": f"KNN 모델 훈련 완료! {len(labels)}개 단어, {len(df)}개 샘플"
    }


@router.get("/predict-test")
def predict_test(handedness: str = "Right"):
    """KNN 모델 로드 및 예측 가능 여부 확인"""
    if not MODEL_PATH.exists():
        return {"ok": False, "message": "훈련된 모델이 없습니다. /train 먼저 실행하세요."}
    model = joblib.load(MODEL_PATH)
    return {
        "ok": True,
        "labels": list(model.classes_),
        "message": "KNN 모델 로드 성공! 예측 준비 완료."
    }
