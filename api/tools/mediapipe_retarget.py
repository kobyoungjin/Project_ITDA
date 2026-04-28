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
# [실측 기반 / 2026-04-24] sonyr.glb GLB 에서 pygltflib 로 추출:
#   - 캐릭터의 오른쪽 팔/손/손가락 = world -X 방향 (RightArm pos x=-0.16)
#   - 캐릭터의 왼쪽  팔/손/손가락 = world +X 방향
# AI Hub 데이터(signer 정면 카메라)와 좌표계 일치 (signer 오른쪽 = -X)
REST_DIRECTIONS = {
    # 상완 + 전완
    "RightArm":     np.array([-1.0, 0.0, 0.0]),
    "LeftArm":      np.array([+1.0, 0.0, 0.0]),
    "RightForeArm": np.array([-1.0, 0.0, 0.0]),
    "LeftForeArm":  np.array([+1.0, 0.0, 0.0]),
    # 손목
    "RightHand":    np.array([-1.0, 0.0, 0.0]),
    "LeftHand":     np.array([+1.0, 0.0, 0.0]),
    # 손가락 — Right 쪽 (world -X 로 뻗음)
    "RightHandThumb1":  np.array([-1.0, 0.0, 0.0]),
    "RightHandThumb2":  np.array([-1.0, 0.0, 0.0]),
    "RightHandThumb3":  np.array([-1.0, 0.0, 0.0]),
    "RightHandIndex1":  np.array([-1.0, 0.0, 0.0]),
    "RightHandIndex2":  np.array([-1.0, 0.0, 0.0]),
    "RightHandIndex3":  np.array([-1.0, 0.0, 0.0]),
    "RightHandMiddle1": np.array([-1.0, 0.0, 0.0]),
    "RightHandMiddle2": np.array([-1.0, 0.0, 0.0]),
    "RightHandMiddle3": np.array([-1.0, 0.0, 0.0]),
    "RightHandRing1":   np.array([-1.0, 0.0, 0.0]),
    "RightHandRing2":   np.array([-1.0, 0.0, 0.0]),
    "RightHandRing3":   np.array([-1.0, 0.0, 0.0]),
    "RightHandPinky1":  np.array([-1.0, 0.0, 0.0]),
    "RightHandPinky2":  np.array([-1.0, 0.0, 0.0]),
    "RightHandPinky3":  np.array([-1.0, 0.0, 0.0]),
    # Left 쪽 (world +X 로 뻗음)
    "LeftHandThumb1":  np.array([+1.0, 0.0, 0.0]),
    "LeftHandThumb2":  np.array([+1.0, 0.0, 0.0]),
    "LeftHandThumb3":  np.array([+1.0, 0.0, 0.0]),
    "LeftHandIndex1":  np.array([+1.0, 0.0, 0.0]),
    "LeftHandIndex2":  np.array([+1.0, 0.0, 0.0]),
    "LeftHandIndex3":  np.array([+1.0, 0.0, 0.0]),
    "LeftHandMiddle1": np.array([+1.0, 0.0, 0.0]),
    "LeftHandMiddle2": np.array([+1.0, 0.0, 0.0]),
    "LeftHandMiddle3": np.array([+1.0, 0.0, 0.0]),
    "LeftHandRing1":   np.array([+1.0, 0.0, 0.0]),
    "LeftHandRing2":   np.array([+1.0, 0.0, 0.0]),
    "LeftHandRing3":   np.array([+1.0, 0.0, 0.0]),
    "LeftHandPinky1":  np.array([+1.0, 0.0, 0.0]),
    "LeftHandPinky2":  np.array([+1.0, 0.0, 0.0]),
    "LeftHandPinky3":  np.array([+1.0, 0.0, 0.0]),
}


# OpenPose hand 21 keypoints 인덱스 (표준)
# 0: wrist
# 1-4:  Thumb (CMC, MCP, IP, TIP)
# 5-8:  Index (MCP, PIP, DIP, TIP)
# 9-12: Middle (MCP, PIP, DIP, TIP)
# 13-16: Ring
# 17-20: Pinky
FINGER_CHAINS = {
    # (손가락 이름, [키포인트 idx 4개], 아바타 본 이름 접미사)
    # 아바타는 3마디 (1, 2, 3) — AI Hub 의 4개 중 처음 3개 (tip 제외) 사용
    "Thumb":  ([1, 2, 3], ["Thumb1", "Thumb2", "Thumb3"]),
    "Index":  ([5, 6, 7], ["Index1", "Index2", "Index3"]),
    "Middle": ([9, 10, 11], ["Middle1", "Middle2", "Middle3"]),
    "Ring":   ([13, 14, 15], ["Ring1", "Ring2", "Ring3"]),
    "Pinky":  ([17, 18, 19], ["Pinky1", "Pinky2", "Pinky3"]),
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

    # [V3.1 변경] WORLD quaternion 으로 저장 (local 계산은 playback 시)
    # 이유: local 끼리 slerp 하면 forearm_world ≠ slerp(fore_world_a, fore_world_b)
    # 꿀렁거림 현상 발생. World 끼리 slerp 하면 수학적으로 정확.
    upper_world = quat_from_unit_vectors(REST_DIRECTIONS[arm_key], upper_target)
    fore_world  = quat_from_unit_vectors(REST_DIRECTIONS[fore_key], fore_target)

    return {
        arm_key: quat_to_dict(upper_world),
        fore_key: quat_to_dict(fore_world),
    }


def _build_full_parent_chain() -> dict:
    """
    V3 JSON 에 들어갈 parent_chain. motion_loader_v3 가 world → local 계산용.
    - RightArm/LeftArm: root (parent = None)
    - ForeArm: Arm 의 자식
    - Hand: ForeArm 의 자식
    - 손가락 마디 1 (Thumb1 등): Hand 의 자식
    - 손가락 마디 2 (Thumb2): 마디 1 의 자식
    - 손가락 마디 3 (Thumb3): 마디 2 의 자식
    """
    chain = {
        "RightArm": None,
        "LeftArm": None,
        "RightForeArm": "RightArm",
        "LeftForeArm": "LeftArm",
        "RightHand": "RightForeArm",
        "LeftHand": "LeftForeArm",
    }
    for side in ("Right", "Left"):
        for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            chain[f"{side}Hand{finger}1"] = f"{side}Hand"
            chain[f"{side}Hand{finger}2"] = f"{side}Hand{finger}1"
            chain[f"{side}Hand{finger}3"] = f"{side}Hand{finger}2"
    return chain


def retarget_hand_chain(hand_kps_3d: list, side: str) -> dict:
    """
    OpenPose 손 21개 keypoint 3D → 손목(Hand) + 손가락 15개 본의 world quaternion.

    hand_kps_3d: flat [x,y,z,conf] × 21 (총 84 float)
    side: "Right" 또는 "Left"

    Returns:
      { "RightHand": {x,y,z,w}, "RightHandIndex1": {...}, ... }
    """
    if not hand_kps_3d or len(hand_kps_3d) < 84:
        return {}

    def pt(idx):
        b = idx * 4
        return np.array([hand_kps_3d[b], -hand_kps_3d[b+1], -hand_kps_3d[b+2]], dtype=float)

    wrist = pt(0)
    # Hand 본: wrist → middle finger MCP 방향을 손목 orientation 으로
    middle_mcp = pt(9)
    hand_dir = vec_normalize(middle_mcp - wrist)

    out = {}
    hand_key = f"{side}Hand"
    hand_world = quat_from_unit_vectors(REST_DIRECTIONS[hand_key], hand_dir)
    out[hand_key] = quat_to_dict(hand_world)

    # 각 손가락 3마디 세그먼트: (MCP→PIP), (PIP→DIP), (DIP→TIP)
    for finger_name, (idx_list, bone_suffixes) in FINGER_CHAINS.items():
        # 세그먼트 정의: mcp=idx_list[0]-1 대신 5,6,7 패턴 → (wrist|mcp, pip, dip)
        # 실제로는 Thumb1 = wrist-mcp 방향, Thumb2 = mcp-ip, Thumb3 = ip-tip
        # Thumb: idx_list=[1,2,3] → segs: (wrist,1), (1,2), (2,3)
        # Index: idx_list=[5,6,7] → segs: (wrist,5), (5,6), (6,7)
        segs = [(0, idx_list[0]), (idx_list[0], idx_list[1]), (idx_list[1], idx_list[2])]
        for i, ((a, b), suffix) in enumerate(zip(segs, bone_suffixes)):
            bone_key = f"{side}Hand{suffix}"
            if bone_key not in REST_DIRECTIONS:
                continue
            seg_dir = vec_normalize(pt(b) - pt(a))
            world_q = quat_from_unit_vectors(REST_DIRECTIONS[bone_key], seg_dir)
            out[bone_key] = quat_to_dict(world_q)

    return out


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
        # OpenPose/MediaPipe 카메라 좌표 → Three.js world 좌표 변환
        #   Y: 아래가 양수 → 위가 양수로 (부호 반전)
        #   Z: 카메라로부터 멀어짐이 양수 → 뷰어 쪽이 양수로 (부호 반전)
        #   X: 동일
        return np.array([d["x"], -d["y"], -d.get("z", 0.0)], dtype=float)

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
# Quaternion 스무딩 — slerp 기반 EMA
# ════════════════════════════════════════════════════════════════
#
# OpenPose 3D 재구성은 프레임마다 잔여 noise 가 있어 각 관절의 quaternion 이
# 독립적으로 떨림. 결과적으로 상완·전완·손목이 서로 다른 속도로 움직여
# "팔이 꿀렁거리는" 현상 발생. EMA 로 noise 를 공유/감쇄.

def quat_slerp(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    """두 quaternion 간 spherical lerp (Three.js Quaternion.slerp 호환)."""
    a = a / (np.linalg.norm(a) + 1e-8)
    b = b / (np.linalg.norm(b) + 1e-8)
    dot = float(np.dot(a, b))
    if dot < 0.0:
        b = -b
        dot = -dot
    if dot > 0.9995:
        # 거의 동일 — linear lerp 로 충분
        result = a + t * (b - a)
        return result / (np.linalg.norm(result) + 1e-8)
    theta_0 = math.acos(max(-1.0, min(1.0, dot)))
    theta = theta_0 * t
    sin_t = math.sin(theta)
    sin_t0 = math.sin(theta_0)
    s1 = math.cos(theta) - dot * sin_t / sin_t0
    s2 = sin_t / sin_t0
    return a * s1 + b * s2


def smooth_quaternion_frames(frames: list[dict], alpha: float = 0.35) -> list[dict]:
    """
    프레임 시퀀스의 각 bone quaternion 에 slerp 기반 EMA 적용.
    alpha 가 클수록 원본에 가까움, 작을수록 부드러움.
    """
    if len(frames) <= 1:
        return frames

    smoothed = [frames[0]]
    prev_bones = {k: np.array([v["x"], v["y"], v["z"], v["w"]])
                  for k, v in frames[0]["bones"].items()}

    for i in range(1, len(frames)):
        curr = frames[i]
        curr_bones = {}
        new_bones = {}
        for bname, q_dict in curr["bones"].items():
            qc = np.array([q_dict["x"], q_dict["y"], q_dict["z"], q_dict["w"]])
            qp = prev_bones.get(bname, qc)
            # EMA: qnew = slerp(qp, qc, alpha)
            # alpha=1 → 완전 현재 채택, alpha=0 → 이전 유지
            q_smooth = quat_slerp(qp, qc, alpha)
            curr_bones[bname] = q_smooth
            new_bones[bname] = {
                "x": round(float(q_smooth[0]), 5),
                "y": round(float(q_smooth[1]), 5),
                "z": round(float(q_smooth[2]), 5),
                "w": round(float(q_smooth[3]), 5),
            }
        smoothed.append({"time": curr["time"], "bones": new_bones})
        prev_bones = curr_bones

    return smoothed


# ════════════════════════════════════════════════════════════════
# Keyframe 압축
# ════════════════════════════════════════════════════════════════

def reduce_keyframes(frames: list[dict], min_delta_rad: float = 0.05) -> list[dict]:
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

# ════════════════════════════════════════════════════════════════
# OpenPose BODY_25 Extractor (AI Hub keypoint 데이터 전용)
# ════════════════════════════════════════════════════════════════
#
# AI Hub 103 keypoint 데이터셋은 영상 대신 OpenPose 형식의 3D 스켈레톤 JSON 을 제공.
# 폴더 구조: NIA_SL_WORD####_REAL##_X/ 안에 프레임별 JSON 150개 정도.
# 각 JSON: {"people": {"pose_keypoints_3d": [...], "hand_left_keypoints_3d": [...], ...}}
# pose_keypoints_3d 는 BODY_25 × (x, y, z, conf) = 100개 float.

# BODY_25 인덱스 (OpenPose 표준)
BODY25 = {
    "Nose": 0, "Neck": 1,
    "RShoulder": 2, "RElbow": 3, "RWrist": 4,
    "LShoulder": 5, "LElbow": 6, "LWrist": 7,
    "MidHip": 8,
}


def _openpose_pose_to_dict(pose_flat: list) -> dict:
    """BODY_25 flat 배열(100 float) → pose_analyzer 호환 dict.

    [중요] 좌표계 변환은 retarget_pose_frame.to_np() 가 담당 (y, z 부호 반전).
    여기서는 raw 값을 그대로 전달 — 두 번 변환되면 학날개 되니 절대 변환 추가 금지.
    """
    def pt(idx):
        base = idx * 4
        return {"x":  pose_flat[base],
                "y":  pose_flat[base + 1],
                "z":  pose_flat[base + 2]}
    return {
        "left_shoulder":  pt(BODY25["LShoulder"]),
        "right_shoulder": pt(BODY25["RShoulder"]),
        "left_elbow":     pt(BODY25["LElbow"]),
        "right_elbow":    pt(BODY25["RElbow"]),
        "left_wrist":     pt(BODY25["LWrist"]),
        "right_wrist":    pt(BODY25["RWrist"]),
    }


def _flip_hand_keypoints(hand_flat: list) -> list:
    """손 keypoint passthrough — 좌표 변환은 retarget_hand_chain 측에서 일관 처리."""
    return hand_flat


def _smooth_positions_centered(frames_raw: list[dict], window: int = 5) -> list[dict]:
    """
    관절 위치에 대해 center-aligned moving average 적용 (zero-lag).
    각 프레임의 keypoint 위치를 ±window//2 프레임 평균으로 대체.
    EMA 같은 phase lag 없이 micro-jitter 제거.
    pose 만 스무딩하고 hand_right/hand_left (flat float list) 은 원본 유지.
    """
    if window < 3 or len(frames_raw) < window:
        return frames_raw
    half = window // 2
    keys = list(frames_raw[0]["pose"].keys())
    out = []
    for i in range(len(frames_raw)):
        lo = max(0, i - half)
        hi = min(len(frames_raw), i + half + 1)
        window_frames = frames_raw[lo:hi]
        new_pose = {}
        for k in keys:
            xs, ys, zs = [], [], []
            for f in window_frames:
                p = f["pose"].get(k)
                if p:
                    xs.append(p["x"]); ys.append(p["y"]); zs.append(p["z"])
            if xs:
                new_pose[k] = {"x": sum(xs)/len(xs),
                               "y": sum(ys)/len(ys),
                               "z": sum(zs)/len(zs)}
        # [중요] 원본 frame 의 hand_right/hand_left 보존 — smoothing 후 retargeting 에서 필요
        out.append({
            "time": frames_raw[i]["time"],
            "pose": new_pose,
            "hand_right": frames_raw[i].get("hand_right", []),
            "hand_left":  frames_raw[i].get("hand_left", []),
        })
    return out


def extract_from_openpose_dir(keypoint_dir: str | Path, word: str,
                               fps: float = 30.0) -> dict:
    """
    AI Hub 103 OpenPose keypoint 폴더 → MOTION_PROFILES_V3 dict.

    keypoint_dir: NIA_SL_WORD####_REAL##_X 폴더 (프레임 JSON 150개 정도)
    word: 저장할 단어 이름
    """
    kd = Path(keypoint_dir)
    json_files = sorted(kd.glob("*_keypoints.json"))
    if not json_files:
        raise FileNotFoundError(f"keypoint JSON 없음: {kd}")

    print(f"[OpenPose] {kd.name} 프레임 {len(json_files)}개 로드...")

    # 1단계: 원본 pose + hand keypoints 수집 (retargeting 전)
    pose_frames = []
    for i, jf in enumerate(json_files):
        try:
            with open(jf, encoding="utf-8") as f:
                data = json.load(f)
            people = data.get("people", {})
            pose_flat = people.get("pose_keypoints_3d") or []
            if len(pose_flat) < 100:
                continue
            pose_dict = _openpose_pose_to_dict(pose_flat)
            # 손 keypoints 도 함께 보관 (retargeting 시 사용) — 동일 좌표계 변환
            pose_frames.append({
                "time": round(i / fps, 4),
                "pose": pose_dict,
                "hand_right": _flip_hand_keypoints(people.get("hand_right_keypoints_3d") or []),
                "hand_left":  _flip_hand_keypoints(people.get("hand_left_keypoints_3d") or []),
            })
        except Exception as e:
            print(f"  경고 {jf.name}: {e}")

    # 2단계: 위치 단계 zero-lag smoothing (pose 만 — hand 는 keypoint 많아 개별 smoothing 영향 적음)
    pose_frames = _smooth_positions_centered(pose_frames, window=5)

    # 3단계: smoothed pose + hand → quaternion retargeting (arm + hand + fingers)
    raw_frames = []
    for pf in pose_frames:
        bones = retarget_pose_frame(pf["pose"])
        # Hand + 손가락 추가
        if pf.get("hand_right"):
            bones.update(retarget_hand_chain(pf["hand_right"], "Right"))
        if pf.get("hand_left"):
            bones.update(retarget_hand_chain(pf["hand_left"], "Left"))
        if bones:
            raw_frames.append({"time": pf["time"], "bones": bones})

    if not raw_frames:
        raise RuntimeError("유효한 pose 프레임 없음")

    # [핵심 수정] Keyframe 압축 제거 — 시간 간격 불균일이 꿀렁거림의 원흉이었음.
    # rest 구간이 과도 압축되어 0.7초간 느린 slerp → jello 현상.
    # 원본 프레임 전부 유지 → 시간 간격 균일(0.033s), 자연스러운 재생.
    # JSON 크기는 ~50KB → ~85KB 로 증가하지만 여전히 경량.
    smoothed = raw_frames
    compact = smoothed  # 압축 없음
    print(f"[OpenPose] keyframe: {len(raw_frames)} 프레임 전부 유지 (등간격 {1/fps*1000:.0f}ms)")

    return {
        "id": word,
        "description": f"auto-generated from OpenPose keypoints {kd.name}",
        "version": "v3",
        "source": "openpose-aihub",
        "space": "world",  # [V3.1] quaternion 은 WORLD space — playback 에서 local 계산
        "parent_chain": _build_full_parent_chain(),
        "fps": fps,
        "keyframes": compact,
    }


def _batch_openpose(args):
    """
    keypoint 루트 (예: [라벨]01_real_word_keypoint/01) 아래 NIA_SL_WORD####_REAL##_<angle> 폴더를
    모두 순회하면서 V3 JSON 생성. 각 WORD 는 지정 angle 하나만 사용.
    """
    from time import time as _now
    root = Path(args.root)
    if not root.exists():
        print(f"[Batch] 루트 없음: {root}")
        return

    angle = args.angle
    pattern = f"*_REAL*_{angle}"
    dirs = sorted([d for d in root.glob(pattern) if d.is_dir()])
    if args.limit:
        dirs = dirs[:args.limit]

    total = len(dirs)
    print(f"[Batch] {root.name} 에서 {total}개 폴더 발견 (angle={angle})")
    if total == 0:
        return

    t0 = _now()
    ok = 0
    fail = 0

    # 중복 WORD ID 제거: WORD0001_REAL01_F 와 WORD0001_REAL17_F 둘 다 있으면 첫 번째만
    seen_words = set()
    for i, d in enumerate(dirs, 1):
        # 폴더 이름에서 WORD ID 추출: NIA_SL_WORD0001_REAL01_F → WORD0001
        parts = d.name.split("_")
        word_id = next((p for p in parts if p.startswith("WORD")), None)
        if not word_id:
            continue
        if word_id in seen_words:
            continue
        seen_words.add(word_id)

        try:
            motion = extract_from_openpose_dir(d, word_id, fps=30.0)
            save_motion_json(motion, args.output)
            ok += 1
            if i % 50 == 0 or i == total:
                elapsed = _now() - t0
                rate = i / elapsed
                eta = (total - i) / rate if rate > 0 else 0
                print(f"[Batch] 진행 {i}/{total} ({i/total*100:.1f}%) "
                      f"속도 {rate:.1f}/s  ETA {eta:.0f}s")
        except Exception as e:
            fail += 1
            print(f"[Batch] 실패 {word_id}: {e}")

    elapsed = _now() - t0
    print(f"\n[Batch] 완료: 성공 {ok}, 실패 {fail}, 경과 {elapsed:.1f}s "
          f"({ok/elapsed:.1f} words/s)")


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

    sp_op = sub.add_parser("extract-openpose",
                           help="AI Hub 103 OpenPose keypoint 폴더 → V3 JSON")
    sp_op.add_argument("--keypoint-dir", required=True,
                       help="NIA_SL_WORD####_REAL##_X 폴더 경로")
    sp_op.add_argument("--word", required=True, help="저장할 단어 이름")
    sp_op.add_argument("--fps", type=float, default=30.0)
    sp_op.add_argument("--output", default=default_output)

    sp_batch = sub.add_parser("batch-openpose",
                              help="AI Hub keypoint 루트에서 모든 WORD*_F 폴더 일괄 변환")
    sp_batch.add_argument("--root", required=True,
                          help="keypoint 루트 (예: C:/.../[라벨]01_real_word_keypoint/01)")
    sp_batch.add_argument("--angle", default="F", choices=["D","F","L","R","U"],
                          help="사용할 카메라 각도 (기본 F=Front)")
    sp_batch.add_argument("--output", default=default_output)
    sp_batch.add_argument("--limit", type=int, default=None,
                          help="테스트용: 최대 N개만 변환")

    sub.add_parser("self-test", help="Synthetic pose 로 수학 검증")

    args = ap.parse_args()

    if args.cmd == "extract-video":
        motion = extract_from_video(args.video, args.word, args.start, args.end)
        save_motion_json(motion, args.output)
    elif args.cmd == "extract-from-morpheme":
        _extract_from_morpheme(args)
    elif args.cmd == "extract-openpose":
        motion = extract_from_openpose_dir(args.keypoint_dir, args.word, fps=args.fps)
        save_motion_json(motion, args.output)
    elif args.cmd == "batch-openpose":
        _batch_openpose(args)
    elif args.cmd == "self-test":
        _self_test()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
