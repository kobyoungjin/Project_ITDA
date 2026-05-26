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
from pathlib import Path
from urllib.parse import urlparse
from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
from typing import List, Optional
import shutil
import cv2
import mediapipe as mp
from api.core.ml_utils import extract_ksl_features, augment_landmarks

router = APIRouter()

# ── 저장 경로 ────────────────────────────────────────────────
# 프로세스의 CWD 와 무관하게 동작하도록 __file__ 기반 절대경로 사용
DATA_DIR = Path(__file__).resolve().parents[2] / "api" / "data" / "ksl_training"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _current_dataset():
    """현재 선택된 모델(main/dialogue)에 맞는 (CSV 경로, 모델 경로)를 반환한다.
    수집·훈련이 항상 '현재 활성 모델'의 데이터셋을 대상으로 동작하게 한다."""
    from api.services.knn_classifier import get_model_type
    if get_model_type() == "dialogue":
        return (DATA_DIR / "ksl_dataset_dialogue.csv",
                DATA_DIR / "knn_model_dialogue.pkl")
    return (DATA_DIR / "ksl_dataset.csv",
            DATA_DIR / "knn_model.pkl")

# ── 영상 수집 허용 도메인 (SSRF 방지) ────────────────────────
# /url 엔드포인트는 서버가 임의 URL을 요청하게 만들 수 있으므로,
# 신뢰된 수어 영상 도메인만 허용한다.
ALLOWED_VIDEO_HOSTS = ("sldict.korean.go.kr",)


def _is_allowed_video_url(url: str) -> bool:
    """수집용 영상 URL이 신뢰 도메인(ALLOWED_VIDEO_HOSTS)을 가리키는지 검증한다."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_VIDEO_HOSTS)


# ── YouTube 다운로드 지원 (yt-dlp) ────────────────────────────
YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "m.youtube.com")


def _is_youtube_url(url: str) -> bool:
    """URL 이 YouTube 영상을 가리키는지 확인."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return any(host == h or host.endswith("." + h) for h in YOUTUBE_HOSTS)


def _download_youtube(url: str, dest: Path) -> bool:
    """yt-dlp 로 YouTube 영상을 dest 에 mp4 로 다운로드. 차단성이므로 별도 스레드에서 호출.
    480p 이하 mp4 를 선호해 다운로드 크기를 줄인다(학습엔 충분)."""
    try:
        import yt_dlp
    except ImportError:
        print("[Collect] yt-dlp 가 설치되지 않았습니다. `pip install yt-dlp` 필요.")
        return False
    ydl_opts = {
        "format": "mp4[height<=480]/mp4/best[ext=mp4]/best",
        "outtmpl": str(dest),
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"[Collect] yt-dlp 다운로드 실패: {e}")
        return False
    return dest.exists() and dest.stat().st_size > 1000

# ── 수집 상태 (인메모리) ─────────────────────────────────────
_collect_state = {
    "active": False,
    "label": "",
    "count": 0,
    "started_at": 0.0,
    "session": "",  # 수집 세션 ID — 누수 없는 평가용 출처(source)
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

class ModelSelectRequest(BaseModel):
    model_type: str


# ── API 엔드포인트 ────────────────────────────────────────────
@router.get("/get-model-type")
def get_current_model_type():
    """현재 활성화된 모델 타입 조회 ('main' 또는 'dialogue')"""
    from api.services.knn_classifier import get_model_type
    return {"ok": True, "model_type": get_model_type()}


@router.post("/select-model")
def select_model(req: ModelSelectRequest):
    """실시간으로 KNN 모델 변경 ('main' 또는 'dialogue')"""
    from api.services.knn_classifier import set_model_type
    try:
        updated_type = set_model_type(req.model_type)
        return {"ok": True, "model_type": updated_type, "message": f"모델이 '{req.model_type}'으로 변경되었습니다."}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.post("/start")
def start_collection(req: StartRequest):
    """수집 모드 시작 (단어 레이블 지정)"""
    from api.core.ml_utils import reset_prev_state
    reset_prev_state() # 수집 시작 시 이전 모션 잔상 제거
    _collect_state["active"] = True
    _collect_state["label"] = req.label.strip()
    _collect_state["count"] = 0
    _collect_state["started_at"] = time.time()
    # 이번 수집 세션 고유 ID — 평가 시 train/test 누수 방지용 출처(source)
    _collect_state["session"] = f"live_{uuid.uuid4().hex[:12]}"
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
    csv_path, model_path = _current_dataset()
    return {
        "active": _collect_state["active"],
        "label": _collect_state["label"],
        "count": _collect_state["count"],
        "csv_exists": csv_path.exists(),
        "model_exists": model_path.exists(),
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
    # 이 라이브 수집 세션을 출처(source)로 기록 → 누수 없는 평가 가능
    source = _collect_state.get("session") or "live_unknown"
    _save_sample(features, label, source)

    _collect_state["count"] += 1
    return {"ok": True, "count": _collect_state["count"], "label": label}


@router.post("/train")
def train_knn(req: TrainRequest):
    """수집된 CSV 데이터로 KNN 모델 훈련"""
    return train_knn_model(req.n_neighbors)

def train_knn_model(n_neighbors: int = 5):
    """내부 학습 로직 — 현재 선택된 모델(main/dialogue)의 데이터셋을 훈련한다."""
    csv_path, model_path = _current_dataset()
    if not csv_path.exists():
        return {"ok": False, "message": "학습 데이터가 없습니다. 먼저 샘플을 수집하세요."}

    import pandas as pd
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.model_selection import cross_val_score

    df_full = pd.read_csv(csv_path, encoding='utf-8')

    # 학습용 DataFrame 만 정제한다 — CSV 원본은 절대 덮어쓰지 않는다.
    # (이전 버그: head(100) 으로 자른 뒤 CSV 를 덮어써서, 갓 수집한 데이터가
    #  오래된 데이터에 밀려 영구 삭제되던 문제를 수정)
    df = df_full.drop_duplicates()  # 완전 중복 행만 제거
    # 클래스 불균형 완화: 단어당 최대 MAX_PER_LABEL 개. 초과 시 '무작위' 추출.
    # (head 는 먼저 들어온 데이터만 남겨 새로 찍은 take 를 버리므로 sample 사용)
    MAX_PER_LABEL = 400
    parts = []
    for _label, grp in df.groupby('label'):
        if len(grp) > MAX_PER_LABEL:
            grp = grp.sample(n=MAX_PER_LABEL, random_state=42)
        parts.append(grp)
    df = pd.concat(parts, ignore_index=True)
    print(f"[Collect] 학습 데이터: CSV {len(df_full)}행 → 학습 {len(df)}행 "
          f"(중복 제거 + 단어당 최대 {MAX_PER_LABEL}개)")

    if len(df) < 10:
        return {"ok": False, "message": f"샘플 수 부족 ({len(df)}개). 최소 10개 이상 필요합니다."}

    # source 는 출처 메타데이터이므로 학습 특징에서 제외
    X = df.drop(columns=["label", "source"], errors="ignore").values
    y = df["label"].values
    labels = sorted(set(y))

    # [개선] n_neighbors 를 데이터 크기에 맞춰 동적으로 조정 (정확도 향상을 위해 7~9 권장)
    final_n = min(max(7, n_neighbors), len(df) // 3)
    if final_n < 1: final_n = 1

    # [개선] 고차원(64차원) 모션 데이터에서는 'minkowski'(유클리드 변형)가 더 안정적인 경우가 많음
    model = KNeighborsClassifier(n_neighbors=final_n, metric="minkowski", p=2, weights="distance")
    
    # 교차 검증으로 정확도 측정
    if len(df) >= 20:
        scores = cross_val_score(model, X, y, cv=min(5, len(labels)), scoring="accuracy")
        accuracy = float(scores.mean())
    else:
        accuracy = None

    model.fit(X, y)
    joblib.dump(model, model_path)

    # [핵심] 저장 후 메모리의 모델을 강제로 갱신 (서버 재시작 불필요)
    from api.services.knn_classifier import reload_model
    reload_model()

    return {
        "ok": True,
        "samples": int(len(df)),
        "labels": labels,
        "label_count": len(labels),
        "accuracy": round(accuracy * 100, 1) if accuracy is not None else "샘플 부족으로 측정 불가",
        "model_path": str(model_path),
        "message": f"KNN 모델 훈련 완료! {len(labels)}개 단어, {len(df)}개 샘플"
    }


@router.post("/video")
async def collect_from_video(label: str, file: UploadFile = File(...)):
    """
    업로드된 비디오 파일에서 랜드마크를 추출하여 학습 데이터에 추가합니다.
    """
    # 클라이언트가 보낸 파일명을 경로에 그대로 쓰면 상위 디렉터리로 탈출(path traversal)할 수 있다.
    # 파일명은 UUID로 대체하고 확장자만 안전하게 보존한다.
    safe_suffix = Path(file.filename or "").suffix or ".mp4"
    temp_path = DATA_DIR / f"temp_{uuid.uuid4()}{safe_suffix}"
    # 업로드된 영상 파일명을 출처(source)로 기록
    source = f"video:{Path(file.filename or 'upload').name}"
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # CPU 집약적인 영상 분석은 별도 스레드에서 실행하여 이벤트 루프를 보호
        saved_count = await anyio.to_thread.run_sync(_process_video_file, temp_path, label, source)

        return {
            "ok": True,
            "label": label,
            "saved_samples": saved_count,
            "message": f"비디오 분석 완료: {saved_count}개의 샘플이 '{label}'로 저장되었습니다."
        }
    except Exception as e:
        return {"ok": False, "message": str(e)}
    finally:
        if temp_path.exists():
            os.remove(temp_path)

@router.post("/url")
async def collect_from_url(label: str, url: str):
    """
    영상 URL에서 랜드마크를 추출하여 학습 데이터에 추가합니다.
    지원: sldict.korean.go.kr 직접 mp4 / YouTube (yt-dlp 사용).
    """
    # sldict.korean.go.kr은 최근 http 접속이 막히는 경우가 있으므로 https로 전환
    if url.startswith("http://sldict.korean.go.kr"):
        url = url.replace("http://", "https://")

    is_youtube = _is_youtube_url(url)
    # [보안] YouTube 가 아니면 신뢰 도메인 허용목록만 통과 (SSRF 방지)
    if not is_youtube and not _is_allowed_video_url(url):
        return {"ok": False, "message": f"허용되지 않은 영상 URL입니다. (sldict 또는 YouTube URL 만 가능)"}

    temp_path = None
    try:
        temp_path = DATA_DIR / f"temp_download_{uuid.uuid4()}.mp4"

        if is_youtube:
            # YouTube: yt-dlp 로 다운로드 (네트워크 차단성이므로 스레드에서 실행)
            ok = await anyio.to_thread.run_sync(_download_youtube, url, temp_path)
            if not ok:
                return {"ok": False, "message": "YouTube 영상 다운로드 실패 (yt-dlp 미설치, 비공개 영상, 또는 차단된 영상)"}
        else:
            # sldict: 직접 mp4 다운로드
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
                response = await client.get(url)
                # 리다이렉트가 허용목록 밖 도메인으로 빠져나가는 우회를 차단
                if not _is_allowed_video_url(str(response.url)):
                    return {"ok": False, "message": "리다이렉트가 허용되지 않은 도메인으로 향했습니다."}
                if response.status_code != 200:
                    return {"ok": False, "message": f"URL 접근 실패 (상태코드: {response.status_code})"}
                # 파일이 너무 작으면 실패로 간주
                if len(response.content) < 1000:
                    return {"ok": False, "message": "유효하지 않은 영상 파일 (크기 너무 작음)"}
                with open(temp_path, "wb") as f:
                    f.write(response.content)

        # 출처(source) 기록 — 같은 URL = 같은 source
        source = f"{'youtube' if is_youtube else 'url'}:{url}"
        # CPU 집약적인 작업은 별도 스레드에서 실행하여 이벤트 루프를 보호
        saved_count = await anyio.to_thread.run_sync(_process_video_file, temp_path, label, source)

        return {
            "ok": True,
            "label": label,
            "saved_samples": saved_count,
            "message": f"{'YouTube' if is_youtube else 'URL'} 분석 완료: {saved_count}개의 샘플이 저장되었습니다."
        }
    except Exception as e:
        return {"ok": False, "message": str(e)}
    finally:
        if temp_path is not None and temp_path.exists():
            os.remove(temp_path)

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

def _process_video_file(video_path: Path, label: str, source: str):
    """
    실제 비디오 분석 (CPU 집약적 작업)
    [증강 적용] 프레임 1개 -> 원본 1 + 증강 8 = 총 9배 샘플 자동 생성
    """
    from api.core.ml_utils import reset_prev_state
    reset_prev_state() # 비디오 시작 시 모션 상태 초기화
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
            
            # [품질 개선] 영상의 앞뒤 구간 제외 (준비 동작 제거)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # '친구'처럼 오인식이 많은 단어는 더 엄격하게(가운데만) 추출
            trim_rate = 0.35 if label == "친구" else 0.2
            start_frame = int(total_frames * trim_rate)
            end_frame = int(total_frames * (1.0 - trim_rate))
            
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

            count = start_frame
            while cap.isOpened() and saved_count < 100 and count < end_frame:
                ret, frame = cap.read()
                if not ret: break
                
                count += 1
                if count % 3 != 0: continue # 추출 밀도 상향 (5 -> 3)
                
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
                        _save_sample(features, label, source)
                        saved_count += 1

                    # 증강 샘플 (팔 관절은 원본 유지, 양손 독립 증강으로 개선)
                    for _ in range(8):
                        if saved_count >= 100: break
                        aug_r = augment_landmarks(right_lms, n=1)[0] if right_lms else None
                        aug_l = augment_landmarks(left_lms, n=1)[0] if left_lms else None
                        
                        aug_feats = extract_ksl_features(aug_r, aug_l, pose_res)
                        if aug_feats:
                            _save_sample(aug_feats, label, source)
                            saved_count += 1

    finally:
        cap.release()
        
    return saved_count

def _save_sample(features, label, source):
    csv_path, _ = _current_dataset()
    is_new = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            header = [f"f{i}" for i in range(len(features))] + ["source", "label"]
            writer.writerow(header)
        writer.writerow(features + [source, label])
