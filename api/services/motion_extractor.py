import os
import json
import requests
import tempfile
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from pathlib import Path

# 경로 설정
BASE_DIR = Path(__file__).parent.parent.parent
MODEL_DIR = BASE_DIR / "api" / "models"
OUTPUT_DIR = BASE_DIR / "frontend" / "data" / "ksl_motions"
VIDEO_MAP_PATH = BASE_DIR / "api" / "data" / "sign_video_urls.json"

POSE_TASK = MODEL_DIR / "pose_landmarker.task"
HAND_TASK = MODEL_DIR / "hand_landmarker.task"

class MotionExtractor:
    def __init__(self):
        self.video_map = {}
        self.load_video_map()
        
    def load_video_map(self):
        if VIDEO_MAP_PATH.exists():
            try:
                with open(VIDEO_MAP_PATH, "r", encoding="utf-8") as f:
                    self.video_map = json.load(f)
            except Exception as e:
                print(f"[Extractor] 지도 로드 실패: {e}")

    def find_video_url(self, word: str):
        if not self.video_map:
            self.load_video_map()
            
        # 0. 입력어 자체의 콤마 처리 (복합어인 경우 첫 번째 단어 우선 시도)
        sub_words = [w.strip() for w in word.split(",")]
        
        # 1. 정확한 매칭 (입력어 전체 또는 개별 단어)
        search_candidates = [word] + sub_words
        for cand in search_candidates:
            if cand in self.video_map:
                return self.video_map[cand]["video_url"]
        
        # 2. 포함 관계 매칭 (사전의 키를 콤마로 분리해서 검색)
        for key, info in self.video_map.items():
            parts = [p.strip() for p in key.split(",")]
            for cand in search_candidates:
                if cand in parts:
                    return info["video_url"]
        return None

    def get_safe_name(self, word: str) -> str:
        """프론트엔드와 동일하게 파일명에서 특수문자 제거"""
        return word.replace("/", "_").replace(",", "_")

    def extract_and_save(self, word: str) -> bool:
        video_url = self.find_video_url(word)
        if not video_url:
            print(f"[Extractor] '{word}' 에 대한 영상을 찾을 수 없습니다.")
            return False
            
        video_url = video_url.replace("http://", "https://")
        safe_name = self.get_safe_name(word)
        output_path = OUTPUT_DIR / f"{safe_name}.json"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        print(f"[Extractor] '{word}' 처리 시작: {video_url}")
        
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            
        try:
            # 영상 다운로드
            resp = requests.get(video_url, timeout=30)
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                f.write(resp.content)

            # MediaPipe 초기화
            BaseOptions = mp.tasks.BaseOptions
            pose_options = vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(POSE_TASK)),
                running_mode=vision.RunningMode.IMAGE
            )
            hand_options = vision.HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(HAND_TASK)),
                running_mode=vision.RunningMode.IMAGE,
                num_hands=2
            )

            all_frames = []
            cap = cv2.VideoCapture(str(tmp_path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            # Streamlit과 동일: ~15fps로 샘플링
            skip = max(1, round(fps / 15))
            target_fps = fps / skip
            
            with (vision.PoseLandmarker.create_from_options(pose_options) as pose_det,
                  vision.HandLandmarker.create_from_options(hand_options) as hand_det):
                
                fi = 0
                while True:
                    ret, frame = cap.read()
                    if not ret: break
                    
                    if fi % skip == 0:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                        
                        pr = pose_det.detect(mp_img)
                        hr = hand_det.detect(mp_img)
                        
                        lh = np.zeros((21, 3))
                        rh = np.zeros((21, 3))
                        for i, handedness in enumerate(hr.handedness):
                            lms = np.array([[lm.x, lm.y, lm.z] for lm in hr.hand_landmarks[i]])
                            if handedness[0].display_name == "Left": 
                                lh = lms
                            else:
                                rh = lms
                                
                        pose = np.zeros((33, 3))
                        if pr.pose_landmarks:
                            pose = np.array([[lm.x, lm.y, lm.z] for lm in pr.pose_landmarks[0]])
                            
                        # 통합 (LH 21 + RH 21 + POSE 33 = 75)
                        combined = np.concatenate([lh, rh, pose], axis=0)
                        all_frames.append(combined.flatten().tolist())
                    fi += 1

            cap.release()

            # JSON 저장 (target_fps 기준으로 저장)
            result = {
                "word": word,
                "fps": round(target_fps, 2),
                "joint_count": 75,
                "frames": all_frames
            }
            
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
                
            print(f"[Extractor] '{word}' 저장 완료 -> {output_path}")
            return True
            
        except Exception as e:
            print(f"[Extractor] 에러 발생: {e}")
            return False
        finally:
            if tmp_path.exists():
                os.unlink(tmp_path)

motion_extractor = MotionExtractor()
