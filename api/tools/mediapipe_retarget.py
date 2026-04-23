"""
mediapipe_retarget.py ─ [Option A / V3 파이프라인]

영상(mp4) 또는 저장된 landmark 시퀀스(JSON) 를 받아
sonyr.glb 아바타 본의 **quaternion keyframe** 으로 retargeting 하는 도구.

핵심 설계 원칙:
  1. Quaternion 기반 (Euler order 이슈 회피 — 우리가 V2.4 에서 겪은 문제)
  2. Local rotation 체인 (Arm → ForeArm → Hand 순으로 부모 역회전 합성)
  3. 모델 독립 (sonyr.glb rest pose 가 T-pose 라는 가정만 사용)
  4. 출력은 MOTION_PROFILES_V3 JSON — quaternion {x,y,z,w} 로 직접 저장

사용 예:
  # 영상에서 뽑기
  python -m api.tools.mediapipe_retarget extract-video \
      --video samples/hello.mp4 --word 안녕하세요 --output data/ksl_motions/

  # Synthetic 수학 검증
  python -m api.tools.mediapipe_retarget self-test

주요 함수:
  - extract_from_video(path, word) → MOTION_PROFILES_V3 dict
  - retarget_frame(landmarks_dict) → {bone: {x,y,z,w}}
  - reduce_keyframes(frames, min_delta) → 압축된 keyframe 리스트
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


# ════════════════════════════════════════════════════════════════
# 수학 유틸 — Quaternion 연산 (scipy 불필요)
# ════════════════════════════════════════════════════════════════

def vec_normalize(v: np.ndarray) -> np.ndarray:
    """벡터 정규화 (zero-vector 방어)."""
    n = np.linalg.norm(v)
    if n < 1e-8:
        return np.array([1.0, 0.0, 0.0])
    return v / n


def quat_from_unit_vectors(v_from: np.ndarray, v_to: np.ndarray) -> np.ndarray:
    """
    두 단위 벡터 사이의 최소 회전을 quaternion [x, y, z, w] 로 반환.
    Three.js Quaternion.setFromUnitVectors 와 동일한 수학.
    """
    v_from = vec_normalize(v_from)
    v_to = vec_normalize(v_to)

    r = float(np.dot(v_from, v_to)) + 1.0

    if r < 1e-6:
        # 180도 회전 — 수직 축을 찾아 회전
        r = 0.0
        if abs(v_from[0]) > abs(v_from[2]):
            axis = np.array([-v_from[1], v_from[0], 0.0])
        else:
            axis = np.array([0.0, -v_from[2], v_from[1]])
    else:
        axis = np.cross(v_from, v_to)

    q = np.array([axis[0], axis[1], axis[2], r], dtype=float)
    n = np.linalg.norm(q)
    if n < 1e-8:
        return np.array([0.0, 0.0, 0.0, 1.0])
    return q / n


def quat_inverse(q: np.ndarray) -> np.ndarray:
    """Unit quaternion 의 역(켤레)."""
    return np.array([-q[0], -q[1], -q[2], q[3]])


def quat_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product: a * b (Three.js Quaternion.multiply 와 동일 순서)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ])


def quat_identity() -> np.ndarray:
    return np.array([0.0, 0.0, 0.0, 1.0])


def quat_to_dict(q: np.ndarray) -> dict:
    return {"x": round(float(q[0]), 5), "y": round(float(q[1]), 5),
            "z": round(float(q[2]), 5), "w": round(float(q[3]), 5)}


def quat_distance(a: np.ndarray, b: np.ndarray) -> float:
    """두 quaternion 간 각도 차이(라디안). keyframe 압축 판정용."""
    dot = abs(float(np.dot(a, b)))
    dot = min(1.0, max(-1.0, dot))
    return 2.0 * math.acos(dot)


# ════════════════════════════════════════════════════════════════
# Rig 규약 — sonyr.glb 기반 (T-pose rest)
# ════════════════════════════════════════════════════════════════

# T-pose 에서 각 본이 "가리키는" 방향 (bone's primary axis in world space at rest).
# MediaPipe world frame 과 동일 계열로 맞춤 (X=오른쪽, Y=위, Z=앞).
REST_DIRECTIONS = {
    "RightArm":     np.array([1.0, 0.0, 0.0]),   # shoulder → elbow: 오른쪽
    "LeftArm":      np.array([-1.0, 0.0, 0.0]),  # shoulder → elbow: 왼쪽
    "RightForeArm": np.array([1.0, 0.0, 0.0]),   # elbow → wrist: 오른쪽
    "LeftForeArm":  np.array([-1.0, 0.0, 0.0]),
}


# ════════════════════════════════════════════════════════════════
# Retargeting 핵심
# ════════════════════════════════════════════════════════════════

def retarget_arm_chain(shoulder: np.ndarray, elbow: np.ndarray, wrist: np.ndarray,
                       side: str) -> dict:
    """
    상완(Arm) + 전완(ForeArm) 에 대한 local quaternion 계산.

    파라미터:
        shoulder, elbow, wrist: world-space 3D 좌표 (MediaPipe pose landmark)
        side: "Right" 또는 "Left"

    반환:
        { "RightArm": {x,y,z,w}, "RightForeArm": {x,y,z,w} } 등

    알고리즘:
        1) Upper arm 의 목표 방향 = (elbow - shoulder) 정규화
        2) ForeArm 의 목표 방향 = (wrist - elbow) 정규화
        3) Upper arm local quat = rotation_from_rest_to_target(rest_dir, target_dir)
        4) ForeArm local quat = upper_arm_quat.inverse * forearm_world_quat
    """
    upper_target = vec_normalize(elbow - shoulder)
    fore_target  = vec_normalize(wrist - elbow)

    arm_key = f"{side}Arm"
    fore_key = f"{side}ForeArm"

    # Upper arm: rest direction → target direction
    upper_local = quat_from_unit_vectors(REST_DIRECTIONS[arm_key], upper_target)

    # ForeArm: 전역 회전을 계산한 뒤 부모(upper arm) 역회전을 곱해 local 로 변환
    fore_world = quat_from_unit_vectors(REST_DIRECTIONS[fore_key], fore_target)
    fore_local = quat_multiply(quat_inverse(upper_local), fore_world)

    return {
        arm_key: quat_to_dict(upper_local),
        fore_key: quat_to_dict(fore_local),
    }


def retarget_pose_frame(pose_landmarks: dict) -> dict:
    """
    MediaPipe pose landmark 1프레임 → 아바타 본 local quaternion dict.

    입력 (pose_analyzer.py 와 동일 스키마):
      {
        "left_shoulder": {x,y,z}, "right_shoulder": {x,y,z},
        "left_elbow": ..., "right_elbow": ...,
        "left_wrist": ..., "right_wrist": ...,
      }

    모든 필수 landmark 가 없으면 빈 dict 반환.
    """
    required = ["left_shoulder", "right_shoulder",
                "left_elbow", "right_elbow",
                "left_wrist", "right_wrist"]
    for key in required:
        if key not in pose_landmarks:
            return {}

    def to_np(d: dict) -> np.ndarray:
        # MediaPipe: y 는 아래가 양수 → 우리 Three.js 와 동일하게 뒤집음
        return np.array([d["x"], -d["y"], d.get("z", 0.0)], dtype=float)

    rs, re, rw = map(to_np, [pose_landmarks["right_shoulder"],
                             pose_landmarks["right_elbow"],
                             pose_landmarks["right_wrist"]])
    ls, le, lw = map(to_np, [pose_landmarks["left_shoulder"],
                             pose_landmarks["left_elbow"],
                             pose_landmarks["left_wrist"]])

    bones = {}
    bones.update(retarget_arm_chain(rs, re, rw, "Right"))
    bones.update(retarget_arm_chain(ls, le, lw, "Left"))
    return bones


# ════════════════════════════════════════════════════════════════
# Keyframe 압축
# ════════════════════════════════════════════════════════════════

def reduce_keyframes(frames: list[dict], min_delta_rad: float = 0.08) -> list[dict]:
    """
    연속 프레임 중 quaternion 변화량이 임계치 미만이면 제거 (노이즈 + 중복 완화).
    첫 프레임과 마지막 프레임은 항상 보존.
    """
    if len(frames) <= 2:
        return frames

    out = [frames[0]]
    prev_bones = {k: np.array([v["x"], v["y"], v["z"], v["w"]])
                  for k, v in frames[0]["bones"].items()}

    for i in range(1, len(frames) - 1):
        curr = frames[i]
        curr_bones = {k: np.array([v["x"], v["y"], v["z"], v["w"]])
                      for k, v in curr["bones"].items()}
        # 모든 본 중 최대 회전 변화
        max_delta = 0.0
        for bname, qc in curr_bones.items():
            qp = prev_bones.get(bname)
            if qp is None:
                max_delta = min_delta_rad + 1  # 신규 본 → 포함
                break
            d = quat_distance(qp, qc)
            if d > max_delta:
                max_delta = d
        if max_delta >= min_delta_rad:
            out.append(curr)
            prev_bones = curr_bones

    out.append(frames[-1])
    return out


# ════════════════════════════════════════════════════════════════
# Video → landmark 시퀀스 추출
# ════════════════════════════════════════════════════════════════

def extract_landmarks_from_video(video_path: str | Path,
                                  start_sec: float = 0.0,
                                  end_sec: Optional[float] = None) -> list[dict]:
    """
    영상에서 MediaPipe Pose 랜드마크 시퀀스 추출.

    반환: [{"time": 0.033, "pose": {...}}, ...]
    pose dict 는 pose_analyzer 호환 스키마.
    """
    try:
        import cv2
        import mediapipe as mp
    except ImportError as e:
        raise ImportError(f"opencv-python / mediapipe 필요: {e}")

    mp_pose = mp.solutions.pose
    P = mp_pose.PoseLandmark

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    start_frame = int(start_sec * fps)
    end_frame = int((end_sec or total / fps) * fps)

    print(f"[Extract] {video_path} fps={fps:.1f} frames={total} "
          f"window={start_sec:.2f}s~{end_sec if end_sec else 'end'}s")

    frames_out = []
    with mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frame_no = start_frame
        while cap.isOpened() and frame_no < end_frame:
            ret, bgr = cap.read()
            if not ret:
                break
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            res = pose.process(rgb)
            if res.pose_landmarks:
                lm = res.pose_landmarks.landmark
                pose_dict = {
                    "left_shoulder":  {"x": lm[P.LEFT_SHOULDER].x,  "y": lm[P.LEFT_SHOULDER].y,  "z": lm[P.LEFT_SHOULDER].z},
                    "right_shoulder": {"x": lm[P.RIGHT_SHOULDER].x, "y": lm[P.RIGHT_SHOULDER].y, "z": lm[P.RIGHT_SHOULDER].z},
                    "left_elbow":     {"x": lm[P.LEFT_ELBOW].x,     "y": lm[P.LEFT_ELBOW].y,     "z": lm[P.LEFT_ELBOW].z},
                    "right_elbow":    {"x": lm[P.RIGHT_ELBOW].x,    "y": lm[P.RIGHT_ELBOW].y,    "z": lm[P.RIGHT_ELBOW].z},
                    "left_wrist":     {"x": lm[P.LEFT_WRIST].x,     "y": lm[P.LEFT_WRIST].y,     "z": lm[P.LEFT_WRIST].z},
                    "right_wrist":    {"x": lm[P.RIGHT_WRIST].x,    "y": lm[P.RIGHT_WRIST].y,    "z": lm[P.RIGHT_WRIST].z},
                }
                frames_out.append({
                    "time": round((frame_no - start_frame) / fps, 4),
                    "pose": pose_dict,
                })
            frame_no += 1

    cap.release()
    print(f"[Extract] 추출된 프레임 수: {len(frames_out)}")
    return frames_out


# ════════════════════════════════════════════════════════════════
# Top-level: Video → MOTION_PROFILES_V3 JSON
# ════════════════════════════════════════════════════════════════

def extract_from_video(video_path: str | Path, word: str,
                        start_sec: float = 0.0, end_sec: Optional[float] = None,
                        min_delta_rad: float = 0.08) -> dict:
    """
    영상을 MOTION_PROFILES_V3 호환 dict 로 변환.

    출력:
      {
        "id": "안녕하세요",
        "description": "auto-generated from video ...",
        "version": "v3",
        "source": "mediapipe",
        "fps": 30.0,
        "keyframes": [
          {"time": 0.0, "bones": {"RightArm": {x,y,z,w}, ...}},
          ...
        ]
      }
    """
    landmark_frames = extract_landmarks_from_video(video_path, start_sec, end_sec)

    raw_frames = []
    for f in landmark_frames:
        bones = retarget_pose_frame(f["pose"])
        if bones:
            raw_frames.append({"time": f["time"], "bones": bones})

    if not raw_frames:
        raise RuntimeError("[Retarget] 유효한 프레임 없음 — pose 감지 실패")

    compact = reduce_keyframes(raw_frames, min_delta_rad)
    print(f"[Retarget] keyframe: {len(raw_frames)} → {len(compact)} (압축률 "
          f"{(1 - len(compact) / len(raw_frames)) * 100:.1f}%)")

    return {
        "id": word,
        "description": f"auto-generated from {Path(video_path).name}",
        "version": "v3",
        "source": "mediapipe",
        "fps": 30.0,
        "keyframes": compact,
    }


def save_motion_json(motion: dict, output_dir: str | Path):
    """MOTION_PROFILES_V3 dict 를 {word}.json 으로 저장 + index.json 자동 갱신."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{motion['id']}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(motion, f, ensure_ascii=False, indent=2)
    print(f"[Save] {out_path}")

    # index.json 자동 업데이트 (디렉토리 내 모든 단어 스캔)
    index_path = out_dir / "index.json"
    actions = sorted([p.stem for p in out_dir.glob("*.json") if p.name != "index.json"])
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"total": len(actions), "actions": actions}, f, ensure_ascii=False, indent=2)
    print(f"[Index] {index_path} 갱신 ({len(actions)}개 단어)")

    return out_path


# ════════════════════════════════════════════════════════════════
# Self-test — synthetic pose 로 수학 검증
# ════════════════════════════════════════════════════════════════

def _self_test():
    """
    MediaPipe 없이 합성 pose 로 retargeting 수학 단독 검증.
    목표: 알려진 포즈(양팔 차렷, 한 손 들기 등)에서 예상한 quaternion 이 나오는지 확인.
    """
    print("=" * 60)
    print("Self-Test: Retargeting 수학 검증 (Synthetic)")
    print("=" * 60)

    # Case 1: T-pose (rest) → 모든 quaternion 이 identity 여야 함
    tpose = {
        "left_shoulder":  {"x": -0.5, "y": 0.0, "z": 0.0},
        "right_shoulder": {"x":  0.5, "y": 0.0, "z": 0.0},
        "left_elbow":     {"x": -1.0, "y": 0.0, "z": 0.0},
        "right_elbow":    {"x":  1.0, "y": 0.0, "z": 0.0},
        "left_wrist":     {"x": -1.5, "y": 0.0, "z": 0.0},
        "right_wrist":    {"x":  1.5, "y": 0.0, "z": 0.0},
    }
    bones = retarget_pose_frame(tpose)
    print("\n[Case 1] T-pose:")
    for b, q in bones.items():
        is_ident = abs(q["x"]) < 1e-3 and abs(q["y"]) < 1e-3 and \
                   abs(q["z"]) < 1e-3 and abs(q["w"] - 1.0) < 1e-3
        mark = "OK " if is_ident else "!! "
        print(f"  [{mark}] {b}: {q}")

    # Case 2: 양팔 차렷 (팔이 아래로) → Arm quaternion 이 -Y 방향 회전
    # MediaPipe 좌표에서 y 아래 = 양수이므로, 우리가 뒤집으면 y 음수가 "아래"
    # Shoulder (0,0,0), Elbow (0, -1, 0) (아래로) → upper_target = (0,-1,0)
    # Rest = (+1,0,0). 회전은 +X → -Y. 이는 -Z 축 중심 -90° (또는 +90°).
    attention = {
        "left_shoulder":  {"x": -0.5, "y": 0.0, "z": 0.0},
        "right_shoulder": {"x":  0.5, "y": 0.0, "z": 0.0},
        "left_elbow":     {"x": -0.5, "y": 1.0, "z": 0.0},   # 아래 (MediaPipe y 양수)
        "right_elbow":    {"x":  0.5, "y": 1.0, "z": 0.0},
        "left_wrist":     {"x": -0.5, "y": 2.0, "z": 0.0},
        "right_wrist":    {"x":  0.5, "y": 2.0, "z": 0.0},
    }
    bones = retarget_pose_frame(attention)
    print("\n[Case 2] 차렷 자세 (양팔 아래):")
    for b, q in bones.items():
        print(f"  {b}: {q}")
    # 검증: RightArm 의 경우 +X → -Y 회전, 이는 Z 축 중심 -90° 회전 → quat ~= (0, 0, -0.707, 0.707)
    r_arm = bones["RightArm"]
    ok = abs(r_arm["z"] + 0.707) < 0.05 and abs(r_arm["w"] - 0.707) < 0.05
    print(f"  [{'OK ' if ok else 'FAIL'}] RightArm Z ~= -0.707, W ~= 0.707 예상 (arms-down = Z축 -90°)")

    # Case 3: 오른손 위로 (shoulder → elbow → wrist 가 위로)
    hands_up = {
        "left_shoulder":  {"x": -0.5, "y": 0.0, "z": 0.0},
        "right_shoulder": {"x":  0.5, "y": 0.0, "z": 0.0},
        "left_elbow":     {"x": -1.0, "y": 0.0, "z": 0.0},
        "right_elbow":    {"x":  0.5, "y": -1.0, "z": 0.0},   # 위로 (MediaPipe y 음수 = 위)
        "left_wrist":     {"x": -1.5, "y": 0.0, "z": 0.0},
        "right_wrist":    {"x":  0.5, "y": -2.0, "z": 0.0},
    }
    bones = retarget_pose_frame(hands_up)
    print("\n[Case 3] 오른팔 위로 만세:")
    for b, q in bones.items():
        print(f"  {b}: {q}")
    # RightArm: +X → +Y 회전 → Z 축 중심 +90° → quat ~= (0, 0, +0.707, 0.707)
    r_arm = bones["RightArm"]
    ok = abs(r_arm["z"] - 0.707) < 0.05 and abs(r_arm["w"] - 0.707) < 0.05
    print(f"  [{'OK ' if ok else 'FAIL'}] RightArm Z ~= +0.707 예상 (만세)")

    # Case 4: 팔꿈치 90° 굽힘 (forearm 이 상완과 직각)
    elbow_bent = {
        "left_shoulder":  {"x": -0.5, "y": 0.0, "z": 0.0},
        "right_shoulder": {"x":  0.5, "y": 0.0, "z": 0.0},
        "left_elbow":     {"x": -1.0, "y": 0.0, "z": 0.0},
        "right_elbow":    {"x":  1.0, "y": 0.0, "z": 0.0},
        "left_wrist":     {"x": -1.5, "y": 0.0, "z": 0.0},
        "right_wrist":    {"x":  1.0, "y": -1.0, "z": 0.0},   # elbow 에서 위로 90°
    }
    bones = retarget_pose_frame(elbow_bent)
    print("\n[Case 4] 오른쪽 팔꿈치 90° (forearm 위로):")
    for b, q in bones.items():
        print(f"  {b}: {q}")

    print("\n" + "=" * 60)


# ════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════

def _extract_from_morpheme(args):
    """AI Hub morpheme JSON 을 읽어 해당 단어 segment 를 자동 추출."""
    morph_path = Path(args.morpheme)
    with open(morph_path, "r", encoding="utf-8") as f:
        morph = json.load(f)

    matches = []
    for seg in morph.get("data", []):
        for attr in seg.get("attributes", []):
            name = (attr.get("name") or "").strip()
            if name == args.word:
                matches.append((seg.get("start", 0), seg.get("end", 0)))

    if not matches:
        print(f"[morpheme] '{args.word}' 세그먼트 없음")
        return

    # 가장 긴 세그먼트 선택
    start, end = max(matches, key=lambda p: p[1] - p[0])
    print(f"[morpheme] '{args.word}' 발견: {start:.2f}s ~ {end:.2f}s")

    motion = extract_from_video(args.video, args.word, start, end)
    save_motion_json(motion, args.output)


def main():
    ap = argparse.ArgumentParser(description="ITDA Option A retargeting pipeline")
    sub = ap.add_subparsers(dest="cmd")

    # 출력 기본값: frontend/data/ksl_motions/ (프론트엔드 로더가 읽는 위치)
    default_output = str(ROOT / "frontend" / "data" / "ksl_motions")

    sp_video = sub.add_parser("extract-video", help="영상 → MOTION_PROFILES_V3 JSON")
    sp_video.add_argument("--video", required=True, help="mp4 경로")
    sp_video.add_argument("--word", required=True, help="저장할 단어 이름")
    sp_video.add_argument("--start", type=float, default=0.0, help="시작 초 (기본 0)")
    sp_video.add_argument("--end", type=float, default=None, help="종료 초 (기본 영상 끝)")
    sp_video.add_argument("--output", default=default_output)

    sp_morph = sub.add_parser("extract-from-morpheme",
                              help="AI Hub morpheme JSON 으로 자동 타임스탬프 + 추출")
    sp_morph.add_argument("--video", required=True, help="mp4 경로")
    sp_morph.add_argument("--morpheme", required=True, help="해당 morpheme JSON 경로")
    sp_morph.add_argument("--word", required=True, help="추출할 단어")
    sp_morph.add_argument("--output", default=default_output)

    sub.add_parser("self-test", help="Synthetic pose 로 수학 검증")

    args = ap.parse_args()

    if args.cmd == "extract-video":
        motion = extract_from_video(args.video, args.word, args.start, args.end)
        save_motion_json(motion, args.output)
    elif args.cmd == "extract-from-morpheme":
        _extract_from_morpheme(args)
    elif args.cmd == "self-test":
        _self_test()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
