"""
convert_raw_npy_to_v3.py

ksl_motions 폴더에 있는 NPY raw 포맷(frames 배열) 파일들을
V3 keyframe(bones: quaternion) 포맷으로 변환합니다.

사용법:
  python api/tools/convert_raw_npy_to_v3.py              # 전체 변환
  python api/tools/convert_raw_npy_to_v3.py --word 대장  # 특정 단어만

NPY raw 포맷: { fps, frames: [[x,y,z] × 75] }
  - 인덱스 0-32 : MediaPipe Pose (33개)
  - 인덱스 33-53: 왼손 21개
  - 인덱스 54-74: 오른손 21개

출력: ksl_motions/{word}.json (V3 keyframe 포맷, 기존 파일 덮어씀)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from api.tools.mediapipe_retarget import (
    retarget_arm_chain,
    retarget_hand_chain,
    smooth_quaternion_frames,
    reduce_keyframes,
    _build_full_parent_chain,
)

KSL_DIR = ROOT / "frontend" / "data" / "ksl_motions"

# MediaPipe Pose 인덱스 (75-landmark 포맷에서 Pose는 0-32)
POSE = {
    "L_S": 11, "R_S": 12,
    "L_E": 13, "R_E": 14,
    "L_W": 15, "R_W": 16,
}


def pts_from_frame(frame: list) -> list:
    """225-value flat array → [{x,y,z}] × 75"""
    pts = []
    for i in range(75):
        pts.append({"x": frame[i*3], "y": frame[i*3+1], "z": frame[i*3+2]})
    return pts


def to_np_pose(pt: dict, flip_y=True, flip_z=True) -> np.ndarray:
    """MediaPipe image coords → Three.js world coords 변환"""
    return np.array([
        pt["x"],
        -pt["y"] if flip_y else pt["y"],
        -pt["z"] if flip_z else pt["z"],
    ], dtype=float)


def hand_to_flat(pts: list, base_idx: int) -> list:
    """
    pts[base_idx..base_idx+20] → OpenPose 형식 flat [x,y,z,conf]×21 (84 floats)
    retarget_hand_chain 의 입력 형식에 맞춤.
    """
    flat = []
    for i in range(21):
        p = pts[base_idx + i]
        flat.extend([p["x"], p["y"], p["z"], 1.0])
    return flat


def is_bad_point(pt: dict, threshold: float = 1.3) -> bool:
    """트래킹 오류로 좌표가 비정상적으로 큰지 확인"""
    return abs(pt["y"]) > threshold or abs(pt["x"]) > threshold


def convert_raw_file(input_path: Path) -> dict | None:
    """NPY raw JSON → V3 dict 변환. 실패 시 None 반환."""
    with open(input_path, encoding="utf-8") as f:
        raw = json.load(f)

    if "frames" not in raw:
        print(f"  [SKIP] 이미 V3 포맷: {input_path.name}")
        return None

    word = raw.get("word", input_path.stem)
    fps = float(raw.get("fps", 15.0))
    frames_raw = raw["frames"]

    print(f"  변환 중: {word} ({len(frames_raw)}프레임, {fps:.1f}fps)")

    bone_frames: list[dict] = []

    for fi, frame in enumerate(frames_raw):
        pts = pts_from_frame(frame)

        bones: dict = {}

        # ── 팔 리깅 ──────────────────────────────────
        ls, rs = pts[POSE["L_S"]], pts[POSE["R_S"]]
        le, re = pts[POSE["L_E"]], pts[POSE["R_E"]]
        lw, rw = pts[POSE["L_W"]], pts[POSE["R_W"]]

        def is_zero(p):
            return p["x"] == 0 and p["y"] == 0 and p["z"] == 0

        if not (is_zero(rs) or is_zero(re) or is_zero(rw)):
            bones.update(retarget_arm_chain(
                to_np_pose(rs), to_np_pose(re), to_np_pose(rw), "Right"
            ))
        if not (is_zero(ls) or is_zero(le) or is_zero(lw)):
            bones.update(retarget_arm_chain(
                to_np_pose(ls), to_np_pose(le), to_np_pose(lw), "Left"
            ))

        # ── 손가락 리깅 ───────────────────────────────
        rh_base = pts[54]
        lh_base = pts[33]

        # 오른손: 손목이 비정상이면 건너뜀
        if not is_zero(rh_base) and not is_bad_point(rh_base):
            # 손가락 끝들 중 bad point가 50% 이상이면 해당 손 건너뜀
            bad_count = sum(1 for off in [4, 8, 12, 16, 20]
                            if is_bad_point(pts[54 + off]))
            if bad_count < 3:
                flat = hand_to_flat(pts, 54)
                bones.update(retarget_hand_chain(flat, "Right"))

        # 왼손
        if not is_zero(lh_base) and not is_bad_point(lh_base):
            bad_count = sum(1 for off in [4, 8, 12, 16, 20]
                            if is_bad_point(pts[33 + off]))
            if bad_count < 3:
                flat = hand_to_flat(pts, 33)
                bones.update(retarget_hand_chain(flat, "Left"))

        dt = 1.0 / fps
        bone_frames.append({"time": round(fi * dt, 4), "bones": bones})

    if not bone_frames:
        print(f"  [ERROR] 유효한 프레임 없음: {word}")
        return None

    # 스무딩 + 키프레임 압축
    smoothed = smooth_quaternion_frames(bone_frames, alpha=0.4)
    keyframes = reduce_keyframes(smoothed, min_delta_rad=0.04)

    # V3 포맷으로 조립
    v3 = {
        "id": word,
        "description": f"{word} (NPY raw → V3 자동 변환)",
        "version": "v3",
        "source": "npy_converted",
        "space": "world",
        "parent_chain": _build_full_parent_chain(),
        "fps": fps,
        "keyframes": keyframes,
    }

    return v3


def main():
    parser = argparse.ArgumentParser(description="NPY raw → V3 keyframe 변환")
    parser.add_argument("--word", type=str, default=None, help="특정 단어만 변환")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 결과만 출력")
    args = parser.parse_args()

    if args.word:
        targets = list(KSL_DIR.glob(f"{args.word}*.json"))
        if not targets:
            print(f"파일 없음: {args.word}")
            return
    else:
        targets = list(KSL_DIR.glob("*.json"))

    converted = 0
    skipped = 0

    for fp in sorted(targets):
        if fp.stem in ("_list", "index", "_mapping"):
            continue

        try:
            v3 = convert_raw_file(fp)
            if v3 is None:
                skipped += 1
                continue

            if not args.dry_run:
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(v3, f, ensure_ascii=False, indent=2)
                print(f"  [OK] 저장: {fp.name} ({len(v3['keyframes'])}개 키프레임)")
            else:
                print(f"  [dry-run] {fp.name} → {len(v3['keyframes'])}개 키프레임")

            converted += 1

        except Exception as e:
            print(f"  [ERROR] {fp.name}: {e}")

    print(f"\n완료: {converted}개 변환, {skipped}개 건너뜀")


if __name__ == "__main__":
    main()
