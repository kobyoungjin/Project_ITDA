"""
generate_handshape_library.py

KSL 22개 canonical 수형을 parametric 정의 → sonyr.glb 본 local quaternion 변환.

Rig 규약 (sonyr.glb 실측):
  - 손가락 primary axis = local +Y (본이 뻗는 방향)
  - Flexion = local +X 축 중심 양의 회전 (θ>0 = 굽힘)
  - Right/Left 동일 (미러 리그)
  - 엄지만 해부학적 rest 각도 포함 → 별도 처리

출력: frontend/data/handshape_library.json
    {
      "version": "v1",
      "shapes": {
        "주먹":  { "RightHandIndex1": {x,y,z,w}, ... 양손 × 15본 },
        "1지":   { ... },
        ...
      }
    }

각 수형은 프레임당 30개 finger bone local quaternion 를 담고 있음.
motion_loader 는 handshape_id → shape lookup → bone.quaternion 에 직접 적용.
"""

from __future__ import annotations
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "frontend" / "data" / "handshape_library.json"


# ────────────────────────────────────────────────────────────────
# 핵심 수학: flexion angle (deg) → local quaternion around +X axis
# ────────────────────────────────────────────────────────────────
def flex_quat(deg: float) -> dict:
    """Finger flexion: rotation around local +X by +deg degrees."""
    rad = math.radians(deg)
    return {
        "x": math.sin(rad / 2),
        "y": 0.0,
        "z": 0.0,
        "w": math.cos(rad / 2),
    }


def abduct_quat(deg: float) -> dict:
    """Finger abduction/adduction: rotation around local +Z (spread in palm plane)."""
    rad = math.radians(deg)
    return {
        "x": 0.0,
        "y": 0.0,
        "z": math.sin(rad / 2),
        "w": math.cos(rad / 2),
    }


def compose(a: dict, b: dict) -> dict:
    """Hamilton product: result = a * b."""
    ax, ay, az, aw = a["x"], a["y"], a["z"], a["w"]
    bx, by, bz, bw = b["x"], b["y"], b["z"], b["w"]
    return {
        "x": aw * bx + ax * bw + ay * bz - az * by,
        "y": aw * by - ax * bz + ay * bw + az * bx,
        "z": aw * bz + ax * by - ay * bx + az * bw,
        "w": aw * bw - ax * bx - ay * by - az * bz,
    }


def identity_quat() -> dict:
    return {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def finger_quat(flex_deg: float, abduct_deg: float = 0.0) -> dict:
    """One joint: flexion + optional abduction (MCP only in practice)."""
    if abs(abduct_deg) < 0.01:
        return flex_quat(flex_deg)
    # Order: abduct first (spread), then flex (curl) in local frame
    return compose(flex_quat(flex_deg), abduct_quat(abduct_deg))


# ────────────────────────────────────────────────────────────────
# 22개 KSL 수형 정의
#
# 각 수형: { finger: [MCP, PIP, DIP] 굽힘각(deg) } + 엄지는 별도
# 굽힘각 0 = 완전히 펴짐, 90 = 직각, 180 = 손바닥에 붙음
# MCP abduction: 손가락 벌림 (+) / 모음 (-)
#
# 엄지는 3단계 (CMC, MCP, IP) — CMC는 opposition(반대편으로) 움직임 포함
# ────────────────────────────────────────────────────────────────

# 편의를 위해 사용되는 각도 프리셋
STRAIGHT = [0, 0, 0]            # 완전히 폄
FULL_CURL = [90, 90, 45]        # 완전히 쥠 (MCP 90, PIP 90, DIP 45 자연스러운 굽힘)
MID_CURL = [45, 60, 30]         # 중간 굽힘
TIP_CURL = [10, 90, 60]         # 손끝만 굽힘 (hook)


HANDSHAPES = {
    # 1. 주먹 (fist) - 모든 손가락 완전 굽힘, 엄지가 검지/중지 감쌈
    "주먹": {
        "Thumb": {"flex": [40, 70, 50], "opposition": 50},
        "Index": FULL_CURL,
        "Middle": FULL_CURL,
        "Ring": FULL_CURL,
        "Pinky": FULL_CURL,
        "spread": 0,
    },
    # 2. 5지 / 손바닥 펴기 (open hand, spread)
    "5지": {
        "Thumb": {"flex": [0, 0, 0], "opposition": 0},
        "Index": STRAIGHT, "Middle": STRAIGHT, "Ring": STRAIGHT, "Pinky": STRAIGHT,
        "spread": 15,  # fingers spread apart
    },
    # 3. 1지 (index only, "one" / pointing)
    "1지": {
        "Thumb": {"flex": [35, 65, 45], "opposition": 40},
        "Index": STRAIGHT,
        "Middle": FULL_CURL, "Ring": FULL_CURL, "Pinky": FULL_CURL,
        "spread": 0,
    },
    # 4. 2지 / V (index + middle)
    "2지": {
        "Thumb": {"flex": [35, 65, 45], "opposition": 40},
        "Index": STRAIGHT, "Middle": STRAIGHT,
        "Ring": FULL_CURL, "Pinky": FULL_CURL,
        "spread": 10,
    },
    # 5. 3지
    "3지": {
        "Thumb": {"flex": [35, 65, 45], "opposition": 40},
        "Index": STRAIGHT, "Middle": STRAIGHT, "Ring": STRAIGHT,
        "Pinky": FULL_CURL,
        "spread": 8,
    },
    # 6. 4지 - 네 손가락 펴고 엄지 접음
    "4지": {
        "Thumb": {"flex": [40, 75, 50], "opposition": 50},
        "Index": STRAIGHT, "Middle": STRAIGHT, "Ring": STRAIGHT, "Pinky": STRAIGHT,
        "spread": 5,
    },
    # 7. 엄지 (thumb up, "good")
    "엄지": {
        "Thumb": {"flex": [0, 0, 0], "opposition": 0},
        "Index": FULL_CURL, "Middle": FULL_CURL, "Ring": FULL_CURL, "Pinky": FULL_CURL,
        "spread": 0,
    },
    # 8. 새끼 (pinky only)
    "새끼": {
        "Thumb": {"flex": [35, 65, 45], "opposition": 40},
        "Index": FULL_CURL, "Middle": FULL_CURL, "Ring": FULL_CURL,
        "Pinky": STRAIGHT,
        "spread": 0,
    },
    # 9. OK (thumb + index circle, others extended)
    "OK": {
        "Thumb": {"flex": [30, 50, 30], "opposition": 45},
        "Index": [45, 30, 20],  # curl to meet thumb
        "Middle": STRAIGHT, "Ring": STRAIGHT, "Pinky": STRAIGHT,
        "spread": 10,
    },
    # 10. ㄱ (L-shape: thumb + index 90°)
    "ㄱ": {
        "Thumb": {"flex": [0, 0, 0], "opposition": 0},
        "Index": STRAIGHT,
        "Middle": FULL_CURL, "Ring": FULL_CURL, "Pinky": FULL_CURL,
        "spread": 0,
    },
    # 11. 납작손 (flat, fingers together)
    "납작손": {
        "Thumb": {"flex": [10, 20, 10], "opposition": 15},
        "Index": STRAIGHT, "Middle": STRAIGHT, "Ring": STRAIGHT, "Pinky": STRAIGHT,
        "spread": 0,  # together, no spread
    },
    # 12. 손날 (knife-edge: flat with thumb adducted)
    "손날": {
        "Thumb": {"flex": [20, 30, 20], "opposition": 10},
        "Index": STRAIGHT, "Middle": STRAIGHT, "Ring": STRAIGHT, "Pinky": STRAIGHT,
        "spread": 0,
    },
    # 13. 갈고리 (claw/hook: bend at MCP, tips curled)
    "갈고리": {
        "Thumb": {"flex": [30, 40, 25], "opposition": 35},
        "Index": [30, 60, 30], "Middle": [30, 60, 30],
        "Ring": [30, 60, 30], "Pinky": [30, 60, 30],
        "spread": 5,
    },
    # 14. 반주먹 (half-fist: MCP bent, tips up)
    "반주먹": {
        "Thumb": {"flex": [30, 55, 40], "opposition": 40},
        "Index": [70, 40, 20], "Middle": [70, 40, 20],
        "Ring": [70, 40, 20], "Pinky": [70, 40, 20],
        "spread": 0,
    },
    # 15. O (round, all fingers curved to form circle)
    "O": {
        "Thumb": {"flex": [30, 40, 30], "opposition": 40},
        "Index": [50, 40, 30], "Middle": [50, 40, 30],
        "Ring": [50, 40, 30], "Pinky": [50, 40, 30],
        "spread": 0,
    },
    # 16. 집게 (pincer: thumb+index together, rest curled)
    "집게": {
        "Thumb": {"flex": [30, 50, 35], "opposition": 55},
        "Index": [40, 25, 15],
        "Middle": FULL_CURL, "Ring": FULL_CURL, "Pinky": FULL_CURL,
        "spread": 0,
    },
    # 17. 꼬부림 (crooked: index+middle bent like hook)
    "꼬부림": {
        "Thumb": {"flex": [35, 65, 45], "opposition": 40},
        "Index": TIP_CURL, "Middle": TIP_CURL,
        "Ring": FULL_CURL, "Pinky": FULL_CURL,
        "spread": 5,
    },
    # 18. 바보 (thumb + pinky, "shaka")
    "엄지새끼": {
        "Thumb": {"flex": [0, 0, 0], "opposition": 10},
        "Index": FULL_CURL, "Middle": FULL_CURL, "Ring": FULL_CURL,
        "Pinky": STRAIGHT,
        "spread": 0,
    },
    # 19. 손바닥모음 (bunched: all fingertips + thumb meet)
    "손바닥모음": {
        "Thumb": {"flex": [25, 30, 25], "opposition": 40},
        "Index": [30, 35, 30], "Middle": [30, 35, 30],
        "Ring": [30, 35, 30], "Pinky": [30, 35, 30],
        "spread": -5,
    },
    # 20. 벌린손 (spread = same as 5지 but emphasized)
    "벌린손": {
        "Thumb": {"flex": [0, 0, 0], "opposition": -10},
        "Index": STRAIGHT, "Middle": STRAIGHT, "Ring": STRAIGHT, "Pinky": STRAIGHT,
        "spread": 25,
    },
    # 21. 꾹쥠 (tight fist, thumb on top)
    "꾹쥠": {
        "Thumb": {"flex": [45, 75, 60], "opposition": 55},
        "Index": [100, 100, 60], "Middle": [100, 100, 60],
        "Ring": [100, 100, 60], "Pinky": [100, 100, 60],
        "spread": -5,
    },
    # 22. Y (thumb + pinky extended)
    "Y": {
        "Thumb": {"flex": [0, 0, 0], "opposition": -5},
        "Index": FULL_CURL, "Middle": FULL_CURL, "Ring": FULL_CURL,
        "Pinky": STRAIGHT,
        "spread": 0,
    },
}


# ────────────────────────────────────────────────────────────────
# 엄지 처리 — 해부학적으로 finger와 회전축이 다름
# 단순화: CMC opposition은 local +Z 축 중심 (abduction과 동일 효과)
# MCP/IP flex는 finger와 동일 local +X 축 중심
# ────────────────────────────────────────────────────────────────

def thumb_bone_quats(side: str, opposition_deg: float, flex_angles: list) -> dict:
    """
    Thumb1(CMC): opposition + flex
    Thumb2(MCP): flex
    Thumb3(IP):  flex

    [수정] opposition 부호 반전 — Right 엄지의 local +Z 축 중심 양의 회전은
    실제로는 엄지를 몸 안쪽(palm 뒷면)으로 보냄. 따라서 -opposition_deg 로 뒤집어야
    palm 앞쪽(다른 손가락 방향)으로 이동 = 해부학적 opposition.
    """
    prefix = f"{side}HandThumb"
    q1 = compose(flex_quat(flex_angles[0]), abduct_quat(-opposition_deg))
    q2 = flex_quat(flex_angles[1])
    q3 = flex_quat(flex_angles[2])
    return {
        f"{prefix}1": q1,
        f"{prefix}2": q2,
        f"{prefix}3": q3,
    }


def finger_bone_quats(side: str, finger: str, joint_angles: list,
                      spread_deg: float, spread_sign: int) -> dict:
    """
    finger: "Index" / "Middle" / "Ring" / "Pinky"
    joint_angles: [MCP, PIP, DIP] 굽힘각
    spread_deg: MCP abduction 크기
    spread_sign: +1 = outward from palm center, -1 = inward
    """
    prefix = f"{side}Hand{finger}"
    mcp = finger_quat(joint_angles[0], spread_deg * spread_sign)
    pip = flex_quat(joint_angles[1])
    dip = flex_quat(joint_angles[2])
    return {
        f"{prefix}1": mcp,
        f"{prefix}2": pip,
        f"{prefix}3": dip,
    }


# 각 손가락의 spread 방향 (손바닥 정면에서 봤을 때):
# 오른손: Index는 왼쪽(-), Middle은 중앙(0), Ring은 오른쪽(+), Pinky는 더 오른쪽(+)
# 왼손: 대칭
SPREAD_SIGNS = {
    "Index": -1,   # 엄지 쪽
    "Middle": 0,   # 중앙
    "Ring": +1,    # 새끼 쪽
    "Pinky": +1.5,
}


def mirror_quat_yz(q: dict) -> dict:
    """Bilateral mirror: Y, Z 성분 반전. Right → Left 변환용."""
    return {"x": q["x"], "y": -q["y"], "z": -q["z"], "w": q["w"]}


def build_handshape(defn: dict) -> dict:
    """단일 수형 정의 → 양손 × 15본 quaternion dict.
    Right 만 계산하고 Left 는 Y/Z 부호 반전으로 미러링 (좌우 대칭 보장)."""
    right_bones = {}
    # 엄지 (Right)
    thumb = defn["Thumb"]
    right_bones.update(thumb_bone_quats("Right", thumb["opposition"], thumb["flex"]))
    # 4 fingers (Right)
    spread = defn.get("spread", 0)
    for finger in ("Index", "Middle", "Ring", "Pinky"):
        angles = defn[finger]
        sign = SPREAD_SIGNS[finger]
        right_bones.update(finger_bone_quats("Right", finger, angles, spread, sign))

    # Left = Right 를 미러 (Y,Z 반전)
    left_bones = {}
    for bn, q in right_bones.items():
        left_name = bn.replace("Right", "Left", 1)
        left_bones[left_name] = mirror_quat_yz(q)

    return {**right_bones, **left_bones}


def main():
    library = {
        "version": "v1",
        "description": "KSL 22 canonical handshapes as local quaternions for sonyr.glb rig",
        "rig": {
            "flexion_axis": "local +X",
            "flexion_sign": "positive = palm-ward curl",
            "finger_primary_axis": "local +Y",
            "applies_to": "Right* and Left* finger bones (15 per hand)",
        },
        "shapes": {},
    }

    for name, defn in HANDSHAPES.items():
        bones = build_handshape(defn)
        library["shapes"][name] = bones

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(library, f, ensure_ascii=False, indent=2)

    print(f"[handshape] {len(library['shapes'])}개 수형 생성 → {OUT_PATH}")
    # 샘플 출력
    first = next(iter(library["shapes"]))
    sample = library["shapes"][first]
    print(f"  sample ({first}): {len(sample)} bones")
    print(f"  bone names: {sorted(sample.keys())[:5]}...")


if __name__ == "__main__":
    main()
