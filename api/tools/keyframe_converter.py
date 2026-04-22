"""
keyframe_converter.py

AI Hub 수어 레코드(골격 프레임) → 아바타 키프레임 JSON 변환기

■ 출력 포맷 (api/data/ksl_motions/{action}.json)
{
  "id":       "고맙습니다",
  "fps":      30,
  "duration": 1.8,
  "keyframes": [
    {
      "time":  0.0,
      "bones": {
        "RightArm":     {"x": -0.8, "y": 0.0, "z": -1.57},
        "RightForeArm": {"x":  1.2, "y": 0.0, "z":  0.0},
        "LeftArm":      {"x": -0.5, "y": 0.0, "z":  1.57},
        ...
      }
    },
    { "time": 0.2, "bones": { ... } },
    ...
  ]
}

■ 저감 전략
  - 연속된 프레임 중 뼈 회전 변화량이 MIN_DELTA 이하인 프레임은 제거
  - 결과적으로 필요한 키프레임만 저장 → 파일 크기 80% 절감
"""

import json
import math
from pathlib import Path
from typing import Optional

from api.tools.skeleton_extractor import extract_from_label_frame

# ── 설정 ──────────────────────────────────────────────────────
OUTPUT_DIR  = Path(__file__).resolve().parents[2] / "api" / "data" / "ksl_motions"
MIN_DELTA   = 0.05   # 라디안 — 이 값 미만 변화는 키프레임 제외 (노이즈 제거)
MAX_ACTIONS = None   # None = 전체 변환 / 숫자로 제한 가능 (테스트 시 100 등)


# ── 보조 함수 ──────────────────────────────────────────────────
def _max_bone_delta(prev: dict, curr: dict) -> float:
    """두 뼈대 딕셔너리 사이 최대 각도 변화량(라디안)을 반환합니다."""
    max_d = 0.0
    for bone, rot in curr.items():
        p = prev.get(bone, {"x": 0.0, "y": 0.0, "z": 0.0})
        for axis in ("x", "y", "z"):
            d = abs(rot.get(axis, 0.0) - p.get(axis, 0.0))
            if d > max_d:
                max_d = d
    return max_d


def _smooth_bones(keyframes: list[dict], alpha: float = 0.35) -> list[dict]:
    """
    Exponential Moving Average 로 떨림(jitter)을 완화합니다.
    alpha가 클수록 원본에 가깝고, 작을수록 더 부드럽습니다.
    """
    if not keyframes:
        return keyframes

    smoothed = [keyframes[0]]
    for i in range(1, len(keyframes)):
        curr = keyframes[i]["bones"]
        prev = smoothed[-1]["bones"]
        new_bones = {}
        for bone in curr:
            p = prev.get(bone, curr[bone])
            new_bones[bone] = {
                axis: p.get(axis, 0.0) + alpha * (curr[bone].get(axis, 0.0) - p.get(axis, 0.0))
                for axis in ("x", "y", "z")
            }
        smoothed.append({"time": keyframes[i]["time"], "bones": new_bones})

    return smoothed


def _add_return_frame(keyframes: list[dict], duration: float) -> list[dict]:
    """마지막에 초기 자세(T-Pose) 복귀 키프레임을 추가합니다."""
    rest = {bone: {"x": 0.0, "y": 0.0, "z": 0.0} for bone in keyframes[-1]["bones"]}
    keyframes.append({"time": duration + 0.5, "bones": rest})
    return keyframes


# ── 핵심 변환 함수 ────────────────────────────────────────────
def convert_record(record: dict) -> Optional[dict]:
    """
    AI Hub 단일 수어 레코드를 키프레임 JSON 으로 변환합니다.

    입력 (aihub_downloader.parse_label_json 출력):
      {
        "action":  "고맙습니다",
        "duration": 1.8,
        "fps":      30,
        "frames": [
          { "frameNo": 1, "keypoints": { "body": [...], "left_hand": [...], "right_hand": [...] } },
          ...
        ]
      }

    출력: 키프레임 JSON dict 또는 None (프레임 없음)
    """
    action  = record.get("action", "unknown")
    fps     = float(record.get("fps", 30))
    frames  = record.get("frames", [])

    if not frames:
        return None

    keyframes = []
    prev_bones: dict = {}

    for i, frame in enumerate(frames):
        time_sec = i / fps
        bones = extract_from_label_frame(frame)

        if not bones:
            continue

        # 변화량이 충분하지 않으면 이 프레임 스킵 (노이즈 제거)
        if prev_bones and _max_bone_delta(prev_bones, bones) < MIN_DELTA:
            continue

        keyframes.append({"time": round(time_sec, 4), "bones": bones})
        prev_bones = bones

    if not keyframes:
        return None

    # 떨림 완화
    keyframes = _smooth_bones(keyframes)

    # 복귀 프레임 추가
    duration = len(frames) / fps
    keyframes = _add_return_frame(keyframes, duration)

    return {
        "id":        action,
        "fps":       fps,
        "duration":  round(duration, 3),
        "keyframes": keyframes,
    }


# ── 배치 변환 + 저장 ──────────────────────────────────────────
def convert_and_save(records: list[dict]) -> dict[str, Path]:
    """
    AI Hub 레코드 목록을 모두 변환하고 OUTPUT_DIR 에 JSON 파일로 저장합니다.

    같은 수어(action)가 여러 개이면 키프레임을 병합(평균)하여 대표 모션 1개 생성.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # action 별로 그룹화
    grouped: dict[str, list[dict]] = {}
    limit = MAX_ACTIONS
    for rec in records:
        action = rec.get("action", "unknown").strip()
        if not action:
            continue
        grouped.setdefault(action, []).append(rec)
        if limit and len(grouped) >= limit:
            break

    saved_paths: dict[str, Path] = {}
    total = len(grouped)

    print(f"\n[Converter] {total}개 수어 변환 시작...")

    for i, (action, recs) in enumerate(grouped.items(), 1):
        print(f"  [{i}/{total}] {action} ({len(recs)}개 샘플)", end=" → ")

        # 샘플이 여러 개면 가장 긴 것(프레임 수 최대) 선택
        best = max(recs, key=lambda r: len(r.get("frames", [])))
        motion = convert_record(best)

        if motion is None:
            print("스킵 (유효 프레임 없음)")
            continue

        out_path = OUTPUT_DIR / f"{action}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(motion, f, ensure_ascii=False, indent=2)

        print(f"키프레임 {len(motion['keyframes'])}개 저장 ({out_path.name})")
        saved_paths[action] = out_path

    print(f"\n[Converter] 완료: {len(saved_paths)}/{total}개 저장됨 → {OUTPUT_DIR}")
    return saved_paths


# ── 인덱스 파일 생성 ──────────────────────────────────────────
def build_index(saved_paths: dict[str, Path]) -> Path:
    """
    변환된 모든 수어의 인덱스 파일(index.json)을 생성합니다.
    프론트엔드에서 사용 가능한 수어 목록 빠르게 조회 가능.
    """
    index = {
        "total": len(saved_paths),
        "actions": sorted(saved_paths.keys()),
    }
    index_path = OUTPUT_DIR / "index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"[Converter] 인덱스 저장: {index_path}  ({len(saved_paths)}개 수어)")
    return index_path


# ── 단독 실행 테스트 ──────────────────────────────────────────
if __name__ == "__main__":
    # 더미 레코드로 변환 로직 테스트
    dummy = {
        "action": "테스트",
        "fps": 30,
        "duration": 1.0,
        "frames": [
            {
                "frameNo": i,
                "keypoints": {
                    "body": [
                        [0.5, 0.3, 0.8], [0.5, 0.4, 0.9],  # NOSE, NECK
                        [0.6, 0.5, 0.9], [0.65, 0.65, 0.85], [0.7, 0.75, 0.8],  # R_SH, R_EL, R_WR
                        [0.4, 0.5, 0.9], [0.35, 0.65, 0.85], [0.3, 0.75, 0.8],  # L_SH, L_EL, L_WR
                    ] + [[0.0, 0.0, 0.0]] * 10,
                    "right_hand": [[0.5 + j * 0.01, 0.5, 0.9] for j in range(21)],
                    "left_hand":  [[0.5 - j * 0.01, 0.5, 0.9] for j in range(21)],
                }
            }
            for i in range(30)
        ]
    }

    motion = convert_record(dummy)
    print(json.dumps(motion, ensure_ascii=False, indent=2))
