"""
augmentation.py - 수어 영상 데이터 증강 라우터

GET  /api/augment/status   -> 파이프라인 진단
POST /api/augment/video    -> 영상 1개 업로드 -> 100개 증강 ZIP 다운로드
"""

import asyncio
import io
import json
import logging
import sys
import tempfile
import urllib.parse
import zipfile
from pathlib import Path

import aiohttp
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from api.core.config import settings
from api.services.video_augmentor import augment_video

_SUPABASE_BUCKET = "sign_train_data"

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_EXT = {".mp4", ".mov", ".avi", ".webm"}


@router.get("/status")
async def augment_status():
    """증강 파이프라인 단계별 진단 엔드포인트."""
    results: dict = {"python": sys.version}

    # cv2
    try:
        import cv2
        results["cv2"] = cv2.__version__
    except Exception as e:
        results["cv2"] = f"ERROR: {e}"

    # mediapipe
    try:
        import mediapipe
        results["mediapipe"] = mediapipe.__version__
    except Exception as e:
        results["mediapipe"] = f"ERROR: {e}"

    # mediapipe.tasks
    try:
        from mediapipe.tasks import python as _mp
        from mediapipe.tasks.python import vision as _vis
        results["mediapipe_tasks"] = "OK"
    except Exception as e:
        results["mediapipe_tasks"] = f"ERROR: {e}"

    # model file
    model_path = (
        Path(__file__).resolve().parents[2] / "api" / "data" / "pose_landmarker_lite.task"
    )
    results["model_file"] = (
        f"OK ({model_path.stat().st_size // 1024} KB)"
        if model_path.exists()
        else f"MISSING: {model_path}"
    )

    # numpy
    try:
        import numpy as np
        results["numpy"] = np.__version__
    except Exception as e:
        results["numpy"] = f"ERROR: {e}"

    ok = all("ERROR" not in str(v) and "MISSING" not in str(v) for v in results.values())
    return JSONResponse({"ok": ok, **results})


@router.post("/video")
async def augment_video_endpoint(
    video: UploadFile = File(..., description="수어 영상 파일 (MP4/MOV/AVI/WebM)"),
    word: str = Form(..., description="수어 단어 레이블 (예: 안녕하세요)"),
):
    """
    수어 영상 1개를 업로드하면 100개의 증강 변형 JSON을 담은 ZIP을 반환합니다.

    증강 방식:
    - Y축 회전 (좌우 카메라 각도 ±10°~30°)
    - X축 기울기 (상하 카메라 각도 ±5°~15°)
    - 좌우 반전
    - 스케일 변형 (80%~120%)
    - 속도 변형 (0.7x~1.5x)
    - 가우시안 노이즈 (3단계)
    - 위 조합 (2~3중)
    """
    ext = Path(video.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식: {ext}. MP4, MOV, AVI, WebM만 가능합니다.",
        )

    word = word.strip()
    if not word:
        raise HTTPException(status_code=400, detail="단어 레이블을 입력해 주세요.")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(await video.read())
        tmp_path = Path(tmp.name)

    try:
        # asyncio.to_thread: 블로킹 작업을 스레드풀로 분리
        # → uvicorn 이벤트 루프 차단 방지 (500/빈응답 원인 제거)
        zip_bytes = await asyncio.to_thread(augment_video, tmp_path, word)
    except ValueError as e:
        logger.error("[Augment] ValueError: %s", e)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("[Augment] Exception: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"증강 처리 오류: {type(e).__name__}: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)

    safe_word = word.replace(" ", "_")
    encoded = urllib.parse.quote(f"ITDA_{safe_word}_x100.zip")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"ITDA_augmented_x100.zip\"; filename*=UTF-8''{encoded}"
        },
    )


@router.post("/upload")
async def upload_to_supabase(
    zip_file: UploadFile = File(..., description="증강 ZIP 파일"),
):
    """ZIP 내 JSON 파일들을 Supabase Storage의 sign_train_data 버킷에 업로드."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        raise HTTPException(
            status_code=503,
            detail="SUPABASE_URL / SUPABASE_SERVICE_KEY 미설정 — .env 파일을 확인하세요.",
        )

    raw = await zip_file.read()

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            try:
                index = json.loads(zf.read("index.json"))
                word = index.get("word", "unknown")
            except Exception:
                raise HTTPException(status_code=422, detail="유효하지 않은 ZIP — index.json 없음")

            file_list = [n for n in zf.namelist() if n.endswith(".json")]
            file_data = {name: zf.read(name) for name in file_list}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"ZIP 파싱 오류: {e}")

    base = f"{settings.SUPABASE_URL}/storage/v1"
    auth = {"Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
            "x-upsert": "true"}

    success, failed = 0, []
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession() as session:
        for name, data in file_data.items():
            url = f"{base}/object/{_SUPABASE_BUCKET}/{word}/{name}"
            try:
                async with session.post(url, headers=auth, data=data, timeout=timeout) as resp:
                    if resp.status in (200, 201):
                        success += 1
                    else:
                        body = await resp.text()
                        failed.append({"file": name, "status": resp.status, "error": body[:120]})
            except Exception as e:
                failed.append({"file": name, "error": str(e)})

    logger.info("[Upload] %s: %d/%d 업로드 완료", word, success, len(file_data))
    return JSONResponse({
        "word": word,
        "bucket": _SUPABASE_BUCKET,
        "path_prefix": f"{word}/",
        "uploaded": success,
        "total": len(file_data),
        "failed_count": len(failed),
        "failed": failed[:5],
    })


# 고정된 bone 순서 (CSV 컬럼 일관성 보장)
_BONE_ORDER = ["RightArm", "RightForeArm", "LeftArm", "LeftForeArm"]
_CSV_HEADER = (
    "word,aug_id,frame_idx,time,"
    + ",".join(f"{b}_{c}" for b in _BONE_ORDER for c in ("x", "y", "z", "w"))
)


@router.post("/to-csv")
async def zip_to_csv(
    zip_file: UploadFile = File(..., description="증강 ZIP 파일"),
):
    """ZIP 안의 100개 JSON 증강 데이터를 CSV 한 파일로 변환해 반환."""
    raw = await zip_file.read()

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            try:
                index = json.loads(zf.read("index.json"))
                word = index.get("word", "unknown")
            except Exception:
                raise HTTPException(status_code=422, detail="유효하지 않은 ZIP — index.json 없음")

            aug_names = sorted(n for n in zf.namelist()
                               if n.endswith(".json") and n != "index.json")
            rows = [_CSV_HEADER]

            for name in aug_names:
                try:
                    motion = json.loads(zf.read(name))
                except Exception:
                    continue

                aug_id = motion.get("aug_id", name.replace(".json", ""))
                for fi, kf in enumerate(motion.get("keyframes", [])):
                    t = kf.get("time", 0.0)
                    bones = kf.get("bones", {})
                    vals = []
                    for bone in _BONE_ORDER:
                        q = bones.get(bone, {})
                        vals += [q.get("x", 0), q.get("y", 0),
                                 q.get("z", 0), q.get("w", 1)]
                    rows.append(f"{word},{aug_id},{fi},{t}," + ",".join(map(str, vals)))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"ZIP 변환 오류: {e}")

    csv_bytes = "\n".join(rows).encode("utf-8-sig")  # BOM 포함 — Excel 한글 깨짐 방지
    safe_word = urllib.parse.quote(f"ITDA_{word}_x100.csv")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"ITDA_augmented_x100.csv\"; filename*=UTF-8''{safe_word}"
        },
    )
