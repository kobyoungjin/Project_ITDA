"""
extract_sldict_joints.py ─ 수어 영상 URL에서 75개 관절(LH21+RH21+POSE33)을 추출해 JSON 저장
"""

import argparse
import json
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import requests
import tempfile
from pathlib import Path
from tqdm import tqdm

# ── 기본 경로 (repo 내부 파일을 기본값으로 사용) ───────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_URLS_JSON = BASE_DIR / "api" / "data" / "sign_video_urls.json"
DEFAULT_OUTPUT_DIR = BASE_DIR / "frontend" / "data" / "joint_cache"
DEFAULT_POSE_MODEL = BASE_DIR / "api" / "models" / "pose_landmarker.task"
DEFAULT_HAND_MODEL = BASE_DIR / "api" / "models" / "hand_landmarker.task"

# 런타임에 argparse 결과로 채워지는 전역 (main 에서 설정)
OUTPUT_DIR = DEFAULT_OUTPUT_DIR
POSE_MODEL = DEFAULT_POSE_MODEL
HAND_MODEL = DEFAULT_HAND_MODEL


def extract_landmarks_from_video(video_url, word):
    """
    영상 URL에서 75개 관절 데이터를 추출하여 JSON으로 저장
    """
    safe_word = word.replace("/", "_").replace(",", "_")
    output_path = OUTPUT_DIR / f"{safe_word}.json"

    if output_path.exists():
        print(f"  > [Skip] {word} (이미 존재함)")
        return True

    print(f"  > [Processing] {word} ...")

    # 영상 다운로드
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        resp = requests.get(video_url, timeout=20)
        resp.raise_for_status()
        with open(tmp_path, "wb") as f:
            f.write(resp.content)

        cap = cv2.VideoCapture(str(tmp_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        # 15fps 정도로 다운샘플링 (웹 성능 고려)
        skip = max(1, round(fps / 15))

        # 모델 옵션
        BaseOptions = mp.tasks.BaseOptions
        pose_opts = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(POSE_MODEL)),
            running_mode=vision.RunningMode.IMAGE
        )
        hand_opts = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(HAND_MODEL)),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=2
        )

        frames_data = []

        with vision.PoseLandmarker.create_from_options(pose_opts) as pose_det, \
             vision.HandLandmarker.create_from_options(hand_opts) as hand_det:

            fi = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if fi % skip == 0:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

                    p_res = pose_det.detect(mp_img)
                    h_res = hand_det.detect(mp_img)

                    # 왼손, 오른손 분리
                    lh = np.zeros((21, 3))
                    rh = np.zeros((21, 3))
                    for i, handedness in enumerate(h_res.handedness):
                        lms = np.array([[lm.x, lm.y, lm.z] for lm in h_res.hand_landmarks[i]])
                        if handedness[0].display_name == "Left":
                            lh = lms
                        else:
                            rh = lms

                    # 포즈
                    pose = np.zeros((33, 3))
                    if p_res.pose_landmarks:
                        pose = np.array([[lm.x, lm.y, lm.z] for lm in p_res.pose_landmarks[0]])

                    # 75개 점 합치기 (LH 21 + RH 21 + POSE 33)
                    combined = np.concatenate([lh, rh, pose], axis=0).flatten().tolist()
                    frames_data.append(combined)
                fi += 1

        cap.release()
        tmp_path.unlink()

        if frames_data:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump({
                    "word": word,
                    "fps": 15,
                    "frames": frames_data
                }, f, ensure_ascii=False)
            print(f"  > [Saved] {output_path.absolute()}")
            return True

    except Exception as e:
        print(f"  > [Error] {word}: {e}")
        if 'tmp_path' in locals():
            tmp_path.unlink(missing_ok=True)
    return False


def main():
    global OUTPUT_DIR, POSE_MODEL, HAND_MODEL

    parser = argparse.ArgumentParser(
        description="수어 영상 URL에서 75개 관절 데이터를 추출해 joint_cache JSON으로 저장"
    )
    parser.add_argument("--urls-json", type=Path, default=DEFAULT_URLS_JSON,
                        help=f"단어→영상URL 매핑 JSON (기본: {DEFAULT_URLS_JSON})")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"JSON 출력 디렉토리 (기본: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--pose-model", type=Path, default=DEFAULT_POSE_MODEL,
                        help=f"MediaPipe pose_landmarker.task (기본: {DEFAULT_POSE_MODEL})")
    parser.add_argument("--hand-model", type=Path, default=DEFAULT_HAND_MODEL,
                        help=f"MediaPipe hand_landmarker.task (기본: {DEFAULT_HAND_MODEL})")
    parser.add_argument("--limit", type=int, default=20,
                        help="처리할 단어 개수 제한 (기본: 20, 0이면 전체)")
    args = parser.parse_args()

    OUTPUT_DIR = args.output_dir
    POSE_MODEL = args.pose_model
    HAND_MODEL = args.hand_model
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    urls_json: Path = args.urls_json
    if not urls_json.exists():
        print(f"오류: {urls_json} 파일을 찾을 수 없습니다.")
        return
    for model_path in (POSE_MODEL, HAND_MODEL):
        if not model_path.exists():
            print(f"오류: MediaPipe 모델을 찾을 수 없습니다: {model_path}")
            return

    with open(urls_json, "r", encoding="utf-8") as f:
        url_map = json.load(f)

    print(f"총 {len(url_map)}개의 단어 데이터를 처리합니다.")

    count = 0
    for word, info in tqdm(url_map.items()):
        if args.limit and count >= args.limit:
            break
        if extract_landmarks_from_video(info['video_url'], word):
            count += 1


if __name__ == "__main__":
    main()
