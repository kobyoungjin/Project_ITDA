import os
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

# ── 설정 ──────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
INTEL_SYL_DIR = Path(r"C:\Users\ComHolic\Downloads\intel_SYL-master")
URLS_JSON = INTEL_SYL_DIR / "sign_video_urls.json"
OUTPUT_DIR = BASE_DIR / "frontend" / "data" / "joint_cache"
POSE_MODEL = INTEL_SYL_DIR / "models" / "pose_landmarker.task"
HAND_MODEL = INTEL_SYL_DIR / "models" / "hand_landmarker.task"

# ── 초기화 ───────────────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
                if not ret: break
                
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
        if 'tmp_path' in locals(): tmp_path.unlink(missing_ok=True)
    return False

def main():
    if not URLS_JSON.exists():
        print(f"오류: {URLS_JSON} 파일을 찾을 수 없습니다.")
        return
        
    with open(URLS_JSON, "r", encoding="utf-8") as f:
        url_map = json.load(f)
        
    print(f"총 {len(url_map)}개의 단어 데이터를 처리합니다.")
    
    # 상위 10개만 우선 테스트로 처리 (필요시 조절)
    count = 0
    for word, info in tqdm(url_map.items()):
        if count >= 20: break # 일단 20개만
        if extract_landmarks_from_video(info['video_url'], word):
            count += 1

if __name__ == "__main__":
    main()
