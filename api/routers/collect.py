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
import time
import uuid
import json
import httpx
import anyio
import joblib
import numpy as np
from pathlib import Path
import cv2
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import shutil
from api.core.ml_utils import extract_ksl_features, augment_landmarks

# MediaPipe Tasks API 모델 경로 (mp.solutions 대신 사용)
_ROOT = Path(__file__).resolve().parents[2]
POSE_MODEL_PATH = _ROOT / "api" / "data" / "pose_landmarker_lite.task"
HAND_MODEL_PATH = _ROOT / "api" / "data" / "hand_landmarker.task"
_HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
)


def _ensure_hand_model() -> None:
    """hand_landmarker.task 없으면 자동 다운로드."""
    if HAND_MODEL_PATH.exists():
        return
    print("[Collect] hand_landmarker.task 다운로드 중...")
    import urllib.request
    urllib.request.urlretrieve(_HAND_MODEL_URL, str(HAND_MODEL_PATH))
    print(f"[Collect] 다운로드 완료: {HAND_MODEL_PATH}")

router = APIRouter()

# ── 저장 경로 (절대 경로 — 서버 실행 위치에 무관) ──────────────
DATA_DIR = Path(__file__).resolve().parents[2] / "api" / "data" / "ksl_training"
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


def _do_reset() -> dict:
    removed = []
    for path in [CSV_PATH, MODEL_PATH]:
        try:
            if path.exists():
                path.unlink()
                removed.append(path.name)
        except Exception:
            pass
    try:
        from api.services.knn_classifier import reload_model
        reload_model()
    except Exception:
        pass
    return {"ok": True, "removed": removed, "message": "데이터 초기화 완료. 처음부터 학습하세요."}

@router.get("/reset")
def reset_get():
    return _do_reset()

@router.post("/reset")
def reset_post():
    return _do_reset()


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
    import traceback
    try:
        return train_knn_model(req.n_neighbors)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e), "trace": traceback.format_exc()})

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
    df = df.groupby('label').head(300).reset_index(drop=True)
    
    if len(df) < original_len:
        print(f"[Collect] 데이터 정제: {original_len} -> {len(df)} (중복 및 초과 샘플 제거)")
        df.to_csv(CSV_PATH, index=False, encoding='utf-8') # 정제된 데이터 덮어쓰기

    if len(df) < 10:
        return {"ok": False, "message": f"샘플 수 부족 ({len(df)}개). 최소 10개 이상 필요합니다."}

    X = df.drop("label", axis=1).to_numpy(dtype=float)
    y = df["label"].to_numpy(dtype=str)
    labels = sorted({str(l) for l in y})

    # [개선] n_neighbors 를 데이터 크기에 맞춰 동적으로 조정
    final_n = min(n_neighbors, len(df) // 2)
    if final_n < 1: final_n = 1

    # [개선] 동작의 '형태'를 중시하는 코사인 유사도(Cosine) 메트릭 적용 및 가중치 강화
    model = KNeighborsClassifier(n_neighbors=final_n, metric="cosine", weights="distance", n_jobs=1)

    # 교차 검증 (n_jobs=1: joblib 멀티프로세싱 비활성화 — FastAPI 스레드 충돌 방지)
    if len(df) >= 20:
        scores = cross_val_score(model, X, y, cv=min(5, len(labels)), scoring="accuracy", n_jobs=1)
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

    saved_count = await anyio.to_thread.run_sync(_process_video_file, temp_path, label)

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

_POSE_KEYS = {
    "left_shoulder": 11, "right_shoulder": 12,
    "left_elbow": 13,    "right_elbow": 14,
    "left_wrist": 15,    "right_wrist": 16,
}


# ── MediaPipe 싱글톤 (매 프레임 재생성 방지) ─────────────────────
_hand_det = None
_pose_det = None


def _get_detectors():
    """HandLandmarker / PoseLandmarker 싱글톤 반환 (최초 1회만 초기화)."""
    global _hand_det, _pose_det
    if _hand_det is not None:
        return _hand_det, _pose_det

    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    _ensure_hand_model()

    hand_opts = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(HAND_MODEL_PATH)),
        running_mode=vision.RunningMode.IMAGE,
        num_hands=2,
        min_hand_detection_confidence=0.5,
    )
    _hand_det = vision.HandLandmarker.create_from_options(hand_opts)

    if POSE_MODEL_PATH.exists():
        pose_opts = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(POSE_MODEL_PATH)),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.3,
        )
        _pose_det = vision.PoseLandmarker.create_from_options(pose_opts)

    return _hand_det, _pose_det


def _mp_tasks_detect(rgb: np.ndarray):
    """
    RGB 이미지 한 장에서 손/포즈 랜드마크 추출.
    싱글톤 landmarker 재사용 — 매 프레임 초기화 오버헤드 제거.
    반환: (right_lms, left_lms, pose_res)
    """
    from mediapipe import Image as MpImage, ImageFormat

    hand_det, pose_det = _get_detectors()

    mp_image = MpImage(
        image_format=ImageFormat.SRGB,
        data=np.ascontiguousarray(rgb, dtype=np.uint8),
    )

    # ── 손 검출 ──────────────────────────────────────────────────
    right_lms, left_lms = None, None
    h = hand_det.detect(mp_image)
    if h.hand_landmarks and h.handedness:
        for i, hh in enumerate(h.handedness):
            if hh[0].score < 0.5:
                continue
            lms = [{"x": lm.x, "y": lm.y, "z": lm.z} for lm in h.hand_landmarks[i]]
            wrist, mid_tip = lms[0], lms[12]
            hand_size = ((wrist["x"] - mid_tip["x"]) ** 2 + (wrist["y"] - mid_tip["y"]) ** 2) ** 0.5
            if hand_size < 0.04:
                continue
            side = hh[0].category_name
            if side == "Right":
                right_lms = lms
            else:
                left_lms = lms

    # ── 포즈 검출 ────────────────────────────────────────────────
    pose_res = None
    if pose_det:
        p = pose_det.detect(mp_image)
        if p.pose_landmarks:
            lm = p.pose_landmarks[0]
            pose_res = {"landmarks": {
                k: {"x": lm[idx].x, "y": lm[idx].y, "z": lm[idx].z, "visibility": lm[idx].visibility}
                for k, idx in _POSE_KEYS.items()
            }}

    return right_lms, left_lms, pose_res


def _process_video_file(video_path: Path, label: str):
    """
    실제 비디오 분석 (CPU 집약적 작업)
    PyAV로 WebM/VP9 포함 모든 브라우저 녹화 포맷 지원.
    MediaPipe Tasks API 사용.
    [증강 적용] 프레임 1개 -> 원본 1 + 증강 8 = 총 9배 샘플 자동 생성
    """
    import av
    saved_count = 0

    # PyAV로 모든 프레임 읽기 (WebM/VP9 지원)
    all_frames = []
    try:
        container = av.open(str(video_path))
        for packet in container.demux(video=0):
            for frame in packet.decode():
                all_frames.append(frame.to_ndarray(format="rgb24"))
        container.close()
    except Exception as e:
        print(f"[Collect] 영상 읽기 실패 ({video_path.name}): {e}")
        return 0

    if not all_frames:
        return 0

    try:
        for count, image in enumerate(all_frames):
            if saved_count >= 300:
                break
            if count % 5 != 0:
                continue

            right_lms, left_lms, pose_res = _mp_tasks_detect(image)

            if right_lms or left_lms:
                features = extract_ksl_features(right_lms, left_lms, pose_res)
                if features:
                    _save_sample(features, label)
                    saved_count += 1

                    for _ in range(29):
                        if saved_count >= 300:
                            break
                        aug_r = augment_landmarks(right_lms, n=1)[0] if right_lms else None
                        aug_l = augment_landmarks(left_lms, n=1)[0] if left_lms else None
                        aug_feats = extract_ksl_features(aug_r, aug_l, pose_res)
                        if aug_feats:
                            _save_sample(aug_feats, label)
                            saved_count += 1
    except Exception as e:
        print(f"[Collect] MediaPipe 처리 오류: {e}")

    return saved_count

def _save_sample(features, label):
    is_new = not CSV_PATH.exists()
    if is_new:
        # BOM 포함으로 신규 파일 생성 → Excel에서 한글 정상 표시
        with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([f"f{i}" for i in range(len(features))] + ["label"])
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(features + [label])


# ── 실시간 인식 ───────────────────────────────────────────────

def _run_mediapipe_on_image(rgb: np.ndarray) -> tuple:
    """단일 RGB 이미지에서 손/포즈 랜드마크 추출 → (right_lms, left_lms, pose_res)"""
    return _mp_tasks_detect(rgb)


@router.post("/predict-frame")
async def predict_frame(frame: UploadFile = File(...)):
    """
    카메라에서 캡처한 단일 JPEG/PNG 프레임 → KNN 예측 결과 반환.
    실시간 인식용 (200~500ms 폴링).
    """
    from api.services.knn_classifier import predict, is_model_ready, get_labels

    if not is_model_ready():
        return JSONResponse({"label": None, "confidence": 0.0,
                             "message": "모델 없음 — 먼저 학습하세요"})

    img_bytes = await frame.read()
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    rgb = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if rgb is None:
        return JSONResponse({"label": None, "confidence": 0.0,
                             "message": "이미지 디코딩 실패"})
    rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)

    right_lms, left_lms, pose_res = await anyio.to_thread.run_sync(
        _run_mediapipe_on_image, rgb
    )

    label, conf = predict(right_lms, left_lms, pose_res)
    return JSONResponse({
        "label": label,
        "confidence": round(conf, 3),
        "known_words": get_labels(),
    })
