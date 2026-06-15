"""
video_augmentor.py - 수어 영상 데이터 증강 (1개 → 100개)

영상 1개에서 MediaPipe 랜드마크를 추출한 뒤,
Y/X 회전·반전·스케일·속도·노이즈를 조합해 100개 변형을 생성합니다.
각 변형은 MOTION_PROFILES_V3 호환 JSON으로 패키징되어 ZIP으로 반환됩니다.
"""

import io
import json
import math
import sys
import zipfile
from pathlib import Path
from typing import Optional

import numpy as np

from api.tools.mediapipe_retarget import (
    retarget_pose_frame,
    smooth_quaternion_frames,
)


_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)
_MODEL_PATH = Path(__file__).resolve().parents[2] / "api" / "data" / "pose_landmarker_lite.task"


def _ensure_model() -> Path:
    """pose_landmarker_lite.task 모델 파일이 없으면 다운로드."""
    if _MODEL_PATH.exists():
        return _MODEL_PATH
    _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    import urllib.request
    print(f"[Augmentor] 모델 다운로드 중... ({_MODEL_URL})")
    urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    print(f"[Augmentor] 모델 저장 완료: {_MODEL_PATH}")
    return _MODEL_PATH


def _extract_landmarks(video_path: str) -> list[dict]:
    """
    MediaPipe 랜드마크 추출 — subprocess 격리 방식.

    MediaPipe의 네이티브 코드 크래시가 서버 프로세스를 종료시키는 것을 방지하기 위해
    별도 Python 프로세스(_mp_worker.py)로 실행하고 JSON 결과를 파싱합니다.
    """
    import json
    import logging
    import subprocess

    _log = logging.getLogger(__name__)
    _log.info("[Augmentor] 랜드마크 추출 시작 (subprocess): %s", video_path)

    worker = Path(__file__).parent / "_mp_worker.py"
    model_path = _ensure_model()

    try:
        proc = subprocess.run(
            [sys.executable, str(worker), str(video_path), str(model_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("랜드마크 추출 시간 초과 (120초)")

    # stderr는 디버그용 로그
    if proc.stderr.strip():
        _log.debug("[Worker stderr]\n%s", proc.stderr.strip())

    if not proc.stdout.strip():
        raise RuntimeError(
            f"Worker 출력 없음 (returncode={proc.returncode})\n"
            f"stderr: {proc.stderr.strip()[:300]}"
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Worker 출력 파싱 실패: {e}\nOutput: {proc.stdout[:300]}"
        )

    if "error" in data:
        tb = data.get("traceback", "")
        if tb:
            _log.error("[Worker] %s\n%s", data["error"], tb)
        raise ValueError(data["error"])

    frames = data.get("frames", [])
    _log.info(
        "[Augmentor] 추출 완료: %d/%d 프레임 감지 (%.0f%%)",
        data.get("detected", len(frames)),
        data.get("total", 0),
        100 * data.get("detected", 0) / data.get("total", 1),
    )
    return frames

# ── 좌우 대칭 키 매핑 ────────────────────────────────────────────
_MIRROR_MAP = {
    "left_shoulder":  "right_shoulder",
    "right_shoulder": "left_shoulder",
    "left_elbow":     "right_elbow",
    "right_elbow":    "left_elbow",
    "left_wrist":     "right_wrist",
    "right_wrist":    "left_wrist",
}


# ── 기하 변환 헬퍼 ───────────────────────────────────────────────

def _shoulder_center(pose: dict) -> tuple[float, float, float]:
    ls = pose.get("left_shoulder", {})
    rs = pose.get("right_shoulder", {})
    if ls and rs:
        return (
            (ls["x"] + rs["x"]) / 2,
            (ls["y"] + rs["y"]) / 2,
            (ls.get("z", 0.0) + rs.get("z", 0.0)) / 2,
        )
    vals = list(pose.values())
    return (
        sum(v["x"] for v in vals) / len(vals),
        sum(v["y"] for v in vals) / len(vals),
        sum(v.get("z", 0.0) for v in vals) / len(vals),
    )


def _rotate_y(pt: dict, cos_a: float, sin_a: float, cx: float, cz: float) -> dict:
    dx = pt["x"] - cx
    dz = pt.get("z", 0.0) - cz
    return {"x": cx + dx * cos_a + dz * sin_a,
            "y": pt["y"],
            "z": cz - dx * sin_a + dz * cos_a}


def _rotate_x(pt: dict, cos_a: float, sin_a: float, cy: float, cz: float) -> dict:
    dy = pt["y"] - cy
    dz = pt.get("z", 0.0) - cz
    return {"x": pt["x"],
            "y": cy + dy * cos_a - dz * sin_a,
            "z": cz + dy * sin_a + dz * cos_a}


def _transform_pose(pose: dict, params: dict,
                    rng: Optional[np.random.Generator]) -> dict:
    """단일 프레임 pose dict에 증강 파라미터 적용."""
    result = {k: {**v} for k, v in pose.items()}

    # 좌우 반전
    if params.get("mirror"):
        result = {
            _MIRROR_MAP.get(k, k): {"x": -v["x"], "y": v["y"], "z": v.get("z", 0.0)}
            for k, v in result.items()
        }

    cx, cy, cz = _shoulder_center(result)

    # Y축 회전 (좌우 카메라 각도 시뮬레이션)
    if "y_rot_deg" in params:
        a = math.radians(params["y_rot_deg"])
        ca, sa = math.cos(a), math.sin(a)
        result = {k: _rotate_y(v, ca, sa, cx, cz) for k, v in result.items()}

    # X축 기울기 (상하 카메라 각도 시뮬레이션)
    if "x_rot_deg" in params:
        a = math.radians(params["x_rot_deg"])
        ca, sa = math.cos(a), math.sin(a)
        result = {k: _rotate_x(v, ca, sa, cy, cz) for k, v in result.items()}

    # 스케일 (어깨 중점 기준)
    if "scale" in params:
        s = params["scale"]
        result = {
            k: {"x": cx + (v["x"] - cx) * s,
                "y": cy + (v["y"] - cy) * s,
                "z": cz + (v.get("z", 0.0) - cz) * s}
            for k, v in result.items()
        }

    # 가우시안 노이즈
    if "noise_sigma" in params and rng is not None:
        sigma = params["noise_sigma"]
        result = {
            k: {"x": v["x"] + float(rng.normal(0, sigma)),
                "y": v["y"] + float(rng.normal(0, sigma)),
                "z": v.get("z", 0.0) + float(rng.normal(0, sigma * 0.5))}
            for k, v in result.items()
        }

    return result


def _apply_speed(frames: list[dict], speed: float) -> list[dict]:
    """시간축 스케일 - speed > 1 빠르게, < 1 느리게."""
    if speed == 1.0:
        return frames
    return [{"time": round(f["time"] / speed, 4), "pose": f["pose"]} for f in frames]


def _augment_sequence(frames: list[dict], params: dict) -> list[dict]:
    """랜드마크 시퀀스에 증강 변환 적용."""
    rng = None
    if "noise_sigma" in params:
        rng = np.random.default_rng(params.get("noise_seed", 0))

    working = _apply_speed(frames, params.get("speed", 1.0))
    return [{"time": f["time"], "pose": _transform_pose(f["pose"], params, rng)}
            for f in working]


def _to_motion_profile(frames: list[dict], word: str, aug_id: str) -> dict:
    """증강된 랜드마크 프레임 → MOTION_PROFILES_V3 dict."""
    bone_frames = []
    for f in frames:
        bones = retarget_pose_frame(f["pose"])
        if bones:
            bone_frames.append({"time": f["time"], "bones": bones})
    if not bone_frames:
        return {}
    smoothed = smooth_quaternion_frames(bone_frames, alpha=0.35)
    return {
        "id": word,
        "aug_id": aug_id,
        "version": "v3",
        "source": "augmented",
        "fps": 30.0,
        "keyframes": smoothed,
    }


# ── 100개 증강 파라미터 정의 ─────────────────────────────────────

def _build_aug_params() -> list[dict]:
    aug = []

    # 1. 원본 (1)
    aug.append({"id": "original"})

    # 2. Y축 회전 - 좌우 각도 (6)
    for angle in [-30, -20, -10, 10, 20, 30]:
        aug.append({"id": f"yrot_{angle:+d}", "y_rot_deg": angle})

    # 3. X축 기울기 - 상하 각도 (6)
    for angle in [-15, -10, -5, 5, 10, 15]:
        aug.append({"id": f"xtilt_{angle:+d}", "x_rot_deg": angle})

    # 4. 좌우 반전 (1)
    aug.append({"id": "mirror", "mirror": True})

    # 5. 반전 + Y회전 (6)
    for angle in [-30, -20, -10, 10, 20, 30]:
        aug.append({"id": f"mir_yrot_{angle:+d}", "mirror": True, "y_rot_deg": angle})

    # 6. 스케일 변형 (8)
    for scale in [0.80, 0.85, 0.90, 0.95, 1.05, 1.10, 1.15, 1.20]:
        aug.append({"id": f"scale_{int(scale * 100):03d}", "scale": scale})

    # 7. 속도 변형 (6)
    for speed in [0.70, 0.80, 0.90, 1.10, 1.20, 1.50]:
        aug.append({"id": f"speed_{int(speed * 100):03d}", "speed": speed})

    # 8. 노이즈 3단계 × 5시드 (15)
    for sigma in [0.010, 0.020, 0.030]:
        for seed in range(5):
            aug.append({"id": f"noise_s{int(sigma * 1000):02d}_r{seed}",
                        "noise_sigma": sigma, "noise_seed": seed})

    # 9. Y회전 + 노이즈 (8)
    for angle in [-20, -10, 10, 20]:
        for sigma in [0.010, 0.020]:
            aug.append({"id": f"yrot_{angle:+d}_n{int(sigma * 1000):02d}",
                        "y_rot_deg": angle, "noise_sigma": sigma, "noise_seed": 0})

    # 10. 스케일 + 속도 (4)
    for scale in [0.90, 1.10]:
        for speed in [0.80, 1.20]:
            aug.append({"id": f"sc{int(scale * 100)}_sp{int(speed * 100)}",
                        "scale": scale, "speed": speed})

    # 11. 반전 + 속도 (4)
    for speed in [0.80, 0.90, 1.10, 1.20]:
        aug.append({"id": f"mir_sp{int(speed * 100)}", "mirror": True, "speed": speed})

    # 12. 반전 + X기울기 (6)
    for angle in [-15, -10, -5, 5, 10, 15]:
        aug.append({"id": f"mir_xtilt_{angle:+d}", "mirror": True, "x_rot_deg": angle})

    # 13. 반전 + 스케일 (8)
    for scale in [0.80, 0.85, 0.90, 0.95, 1.05, 1.10, 1.15, 1.20]:
        aug.append({"id": f"mir_sc{int(scale * 100):03d}", "mirror": True, "scale": scale})

    # 14. X기울기 + 노이즈 (8)
    for angle in [-10, -5, 5, 10]:
        for sigma in [0.010, 0.020]:
            aug.append({"id": f"xtilt_{angle:+d}_n{int(sigma * 1000):02d}",
                        "x_rot_deg": angle, "noise_sigma": sigma, "noise_seed": 1})

    # 15. 속도 + 노이즈 (6)
    for speed in [0.80, 0.90, 1.20]:
        for sigma in [0.010, 0.020]:
            aug.append({"id": f"sp{int(speed * 100)}_n{int(sigma * 1000):02d}",
                        "speed": speed, "noise_sigma": sigma, "noise_seed": 2})

    # 16. 3중 조합 (7)
    aug += [
        {"id": "yrot+10_sc110_sp090", "y_rot_deg": 10,  "scale": 1.10, "speed": 0.90},
        {"id": "yrot-10_sc090_sp110", "y_rot_deg": -10, "scale": 0.90, "speed": 1.10},
        {"id": "mir_yrot+10_n010",    "mirror": True, "y_rot_deg": 10,  "noise_sigma": 0.010, "noise_seed": 3},
        {"id": "mir_yrot-10_n020",    "mirror": True, "y_rot_deg": -10, "noise_sigma": 0.020, "noise_seed": 3},
        {"id": "sc110_sp080_n010",    "scale": 1.10, "speed": 0.80, "noise_sigma": 0.010, "noise_seed": 4},
        {"id": "sc090_sp120_n010",    "scale": 0.90, "speed": 1.20, "noise_sigma": 0.010, "noise_seed": 4},
        {"id": "mir_sc110_sp090",     "mirror": True, "scale": 1.10, "speed": 0.90},
    ]

    assert len(aug) == 100, f"증강 파라미터 수 오류: {len(aug)}"
    return aug


AUG_PARAMS = _build_aug_params()


# ── 공개 API ─────────────────────────────────────────────────────

def augment_video(video_path: str | Path, word: str) -> bytes:
    """
    영상 1개 → 100개 증강 ZIP (bytes) 반환.

    ZIP 내부 구조:
      {word}_original.json
      {word}_yrot_+10.json
      ...
      index.json
    """
    video_path = Path(video_path)

    # 1. 랜드마크 1회 추출
    landmark_frames = _extract_landmarks(str(video_path))
    if not landmark_frames:
        raise ValueError(
            "MediaPipe 랜드마크 추출 실패 - 영상에서 사람이 감지되지 않았습니다."
        )

    # 2. 100개 증강 생성 + ZIP 패키징
    buf = io.BytesIO()
    meta: list[dict] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, params in enumerate(AUG_PARAMS):
            aug_id = params["id"]
            try:
                aug_frames = _augment_sequence(landmark_frames, params)
                motion = _to_motion_profile(aug_frames, word, aug_id)
                if not motion:
                    meta.append({"index": i + 1, "aug_id": aug_id, "error": "빈 프레임"})
                    continue
                filename = f"{word}_{aug_id}.json"
                zf.writestr(
                    filename,
                    json.dumps(motion, ensure_ascii=False, separators=(",", ":")),
                )
                meta.append({
                    "index": i + 1,
                    "aug_id": aug_id,
                    "file": filename,
                    "frames": len(motion["keyframes"]),
                })
            except Exception as e:
                meta.append({"index": i + 1, "aug_id": aug_id, "error": str(e)})

        success = sum(1 for m in meta if "error" not in m)
        zf.writestr(
            "index.json",
            json.dumps(
                {"word": word, "source": video_path.name,
                 "total": success, "augmentations": meta},
                ensure_ascii=False, indent=2,
            ),
        )

    buf.seek(0)
    return buf.read()
