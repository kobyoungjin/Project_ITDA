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
import uuid
import json
import httpx
import anyio
import joblib
import numpy as np
from pathlib import Path
from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
from typing import List, Optional
import shutil
import cv2
import mediapipe as mp
from api.core.ml_utils import extract_ksl_features, augment_landmarks

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
    # 양손 랜드마크 (각 21개)
    right_landmarks: Optional[List[dict]] = None
    left_landmarks: Optional[List[dict]] = None
    # [NEW] 팔 관절 랜드마크
    pose_landmarks: Optional[dict] = None
    # 하위 호환성을 위해 유지
    landmarks: Optional[List[dict]] = None
    handedness: Optional[str] = "Right"

class TrainRequest(BaseModel):
    n_neighbors: int = 5


from api.core.ml_utils import extract_ksl_features


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

    # 양손 데이터 우선 사용, 없으면 기존 단일 손 데이터 사용
    r_lms = req.right_landmarks
    l_lms = req.left_landmarks
    pose_lms = req.pose_landmarks
    
    if r_lms is None and l_lms is None and req.landmarks:
        if req.handedness == "Right":
            r_lms = req.landmarks
        else:
            l_lms = req.landmarks

    # [개선] 팔 관절 데이터 포함
    features = extract_ksl_features(r_lms, l_lms, pose_lms)
    if features is None:
        return {"ok": False, "message": "랜드마크 데이터 불충분"}

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
    return train_knn_model(req.n_neighbors)

def train_knn_model(n_neighbors: int = 5):
    """내부 학습 로직"""
    if not CSV_PATH.exists():
        return {"ok": False, "message": "학습 데이터가 없습니다. 먼저 샘플을 수집하세요."}

    import pandas as pd
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.model_selection import cross_val_score

    df = pd.read_csv(CSV_PATH, encoding='utf-8')
    
    # [NEW] 사용자 데이터 병합 최적화 (Task 3)
    original_len = len(df)
    df = df.drop_duplicates() # 중복 노이즈 제거
    # 클래스 불균형 해소: 단어당 최대 100개 샘플만 사용하여 오버피팅 방지
    df = df.groupby('label').head(100).reset_index(drop=True)
    
    if len(df) < original_len:
        print(f"[Collect] 데이터 정제: {original_len} -> {len(df)} (중복 및 초과 샘플 제거)")
        df.to_csv(CSV_PATH, index=False, encoding='utf-8') # 정제된 데이터 덮어쓰기

    if len(df) < 10:
        return {"ok": False, "message": f"샘플 수 부족 ({len(df)}개). 최소 10개 이상 필요합니다."}

    X = df.drop("label", axis=1).values
    y = df["label"].values
    labels = sorted(set(y))

    # [개선] n_neighbors 를 데이터 크기에 맞춰 동적으로 조정
    final_n = min(n_neighbors, len(df) // 2)
    if final_n < 1: final_n = 1

    # [개선] 동작의 '형태'를 중시하는 코사인 유사도(Cosine) 메트릭 적용 및 가중치 강화
    model = KNeighborsClassifier(n_neighbors=final_n, metric="cosine", weights="distance")
    
    # 교차 검증으로 정확도 측정
    if len(df) >= 20:
        scores = cross_val_score(model, X, y, cv=min(5, len(labels)), scoring="accuracy")
        accuracy = float(scores.mean())
    else:
        accuracy = None

    model.fit(X, y)
    joblib.dump(model, MODEL_PATH)

    # [핵심] 저장 후 메모리의 모델을 강제로 갱신 (서버 재시작 불필요)
    from api.services.knn_classifier import reload_model
    reload_model()

    return {
        "ok": True,
        "samples": int(len(df)),
        "labels": labels,
        "label_count": len(labels),
        "accuracy": round(accuracy * 100, 1) if accuracy else "샘플 부족으로 측정 불가",
        "model_path": str(MODEL_PATH),
        "message": f"KNN 모델 훈련 완료! {len(labels)}개 단어, {len(df)}개 샘플"
    }


@router.post("/video")
async def collect_from_video(label: str, file: UploadFile = File(...)):
    """
    업로드된 비디오 파일에서 랜드마크를 추출하여 학습 데이터에 추가합니다.
    """
    temp_path = DATA_DIR / f"temp_{uuid.uuid4()}_{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    saved_count = _process_video_file(temp_path, label)
    
    if temp_path.exists():
        os.remove(temp_path)

    return {
        "ok": True,
        "label": label,
        "saved_samples": saved_count,
        "message": f"비디오 분석 완료: {saved_count}개의 샘플이 '{label}'로 저장되었습니다."
    }

@router.post("/url")
async def collect_from_url(label: str, url: str):
    """
    영상 URL에서 직접 랜드마크를 추출하여 학습 데이터에 추가합니다.
    """
    # sldict.korean.go.kr은 최근 http 접속이 막히는 경우가 있으므로 https로 전환
    if url.startswith("http://sldict.korean.go.kr"):
        url = url.replace("http://", "https://")

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return {"ok": False, "message": f"URL 접근 실패 (상태코드: {response.status_code})"}
            
            # 파일이 너무 작으면 실패로 간주
            if len(response.content) < 1000:
                return {"ok": False, "message": "유효하지 않은 영상 파일 (크기 너무 작음)"}
            
            temp_path = DATA_DIR / f"temp_download_{uuid.uuid4()}.mp4"
            with open(temp_path, "wb") as f:
                f.write(response.content)
            
        # CPU 집약적인 작업은 별도 스레드에서 실행하여 이벤트 루프를 보호
        saved_count = await anyio.to_thread.run_sync(_process_video_file, temp_path, label)
        
        if temp_path.exists():
            os.remove(temp_path)
            
        return {
            "ok": True, 
            "label": label, 
            "saved_samples": saved_count,
            "message": f"URL 분석 완료: {saved_count}개의 샘플이 저장되었습니다."
        }
    except Exception as e:
        return {"ok": False, "message": str(e)}

@router.post("/batch")
async def collect_batch(limit_words: int = 50):
    """
    sign_video_urls.json 파일에서 상위 N개 단어를 자동으로 학습합니다.
    """
    print(f"\n[Batch] 자동 학습 시작 (대상: 상위 {limit_words}개 단어)")
    urls_path = Path("api/data/sign_video_urls.json")
    if not urls_path.exists():
        return {"ok": False, "message": "사전 영상 데이터(json)가 없습니다."}
    
    with open(urls_path, "r", encoding="utf-8") as f:
        urls_data = json.load(f)
    
    items = list(urls_data.items())[:limit_words]
    results = []
    total_samples = 0
    
    for i, (label, info) in enumerate(items):
        url = info.get("video_url")
        if not url: continue
        
        print(f"[Batch] ({i+1}/{limit_words}) '{label}' 분석 시도 중... ", end="", flush=True)
        try:
            # 개별 URL 분석 (기존 로직 재사용)
            res = await collect_from_url(label, url)
            if res["ok"]:
                total_samples += res["saved_samples"]
                results.append(f"{label}: {res['saved_samples']}개")
                print(f"성공 ({res['saved_samples']}개 추출)")
            else:
                print(f"실패 ({res.get('message')})")
        except Exception as e:
            print(f"에러 발생: {e}")
            continue
            
    print(f"[Batch] 모든 영상 처리 완료. 모델 훈련을 시작합니다.")
    train_res = await anyio.to_thread.run_sync(train_knn_model)
    
    return {
        "ok": True,
        "message": f"{len(results)}개 단어 학습 완료 (총 {total_samples} 샘플)",
        "details": results,
        "train_result": train_res
    }

def _process_video_file(video_path: Path, label: str):
    """
    실제 비디오 분석 (CPU 집약적 작업)
    [증강 적용] 프레임 1개 -> 원본 1 + 증강 8 = 총 9배 샘플 자동 생성
    """
    mp_hands = mp.solutions.hands
    mp_pose = mp.solutions.pose
    saved_count = 0
    
    POSE_KEYS = {
        "left_shoulder": 11, "right_shoulder": 12,
        "left_elbow": 13,    "right_elbow": 14,
        "left_wrist": 15,    "right_wrist": 16,
    }

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0

    try:
        with mp_hands.Hands(static_image_mode=False, max_num_hands=2, min_detection_confidence=0.5, min_tracking_confidence=0.5) as hands, \
             mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5) as pose:
            
            count = 0
            while cap.isOpened() and saved_count < 100:
                ret, frame = cap.read()
                if not ret: break
                
                count += 1
                if count % 5 != 0: continue
                
                image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res_hands = hands.process(image)
                res_pose = pose.process(image)
                
                pose_res = None
                if res_pose.pose_landmarks:
                    lm_dict = {}
                    for k, idx in POSE_KEYS.items():
                        lm = res_pose.pose_landmarks.landmark[idx]
                        lm_dict[k] = {"x": lm.x, "y": lm.y, "z": lm.z, "visibility": lm.visibility}
                    pose_res = {"landmarks": lm_dict}

                if res_hands.multi_hand_landmarks:
                    right_lms = None
                    left_lms = None
                    if res_hands.multi_handedness:
                        for idx, hand_handedness in enumerate(res_hands.multi_handedness):
                            label_side = hand_handedness.classification[0].label
                            hlm = res_hands.multi_hand_landmarks[idx]
                            lms = [{"x": lm.x, "y": lm.y, "z": lm.z} for lm in hlm.landmark]
                            if label_side == "Right": right_lms = lms
                            else: left_lms = lms
                    
                    # 원본 저장
                    features = extract_ksl_features(right_lms, left_lms, pose_res)
                    if features:
                        _save_sample(features, label)
                        saved_count += 1

                    # 증강 샘플 (팔 관절은 원본 유지)
                    aug_base = right_lms or left_lms
                    if aug_base and saved_count < 100:
                        for aug_lms in augment_landmarks(aug_base, n=8):
                            if saved_count >= 100: break
                            aug_r = aug_lms if right_lms else None
                            aug_l = aug_lms if left_lms else None
                            aug_feats = extract_ksl_features(aug_r, aug_l, pose_res)
                            if aug_feats:
                                _save_sample(aug_feats, label)
                                saved_count += 1

    finally:
        cap.release()
        
    return saved_count

def _save_sample(features, label):
    is_new = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            header = [f"f{i}" for i in range(len(features))] + ["label"]
            writer.writerow(header)
        writer.writerow(features + [label])
