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
DIALOGUE_WORDS_MAP = {
    "안녕하세요": "안녕하세요,안녕하십니까,안녕히 가십시오,안녕히 계세요",
    "처음": "처음,시작,우선,초",
    "만나다": "만나다",
    "반갑다": "반갑다,반기다,재미,흥,흥취,희열,즐겁다,즐기다",
    "나": "자신,나,저,내",
    "정말": "사실,정말,진짜,참,맞다,정말로",
    "이름": "이름,명,성명,성함",
    "농어": "농인,농아인",
    "당신": "당신",
    "무엇": "어느,무엇,어떤,무슨,뭐,아무,어디",
    "청인": "난청인,난청자",
    "좋다": "좋다,선",
    "혹시": "혹시,혹,혹여",
    "말": "말,말하다,언어",
    "잘": "잘하다,잘",
    "들리다": "듣다,소리,소식,청각",
    "네": "너,네,자네",
    "아주": "크다,꽤,매우,몹시,무척,아주,대,대단히",
    "목소리": "목소리,음성,발음,목청,언성,부르다",
    "참": "사실,정말,진짜,참,맞다,정말로",
    "행복": "행복,복",
    "발음": "목소리,음성,발음,목청,언성,부르다",
    "조금": "작다,다소,약간,조금,약소하다,자그마하다,적다,조그마하다",
    "서툴다": "미숙하다",
    "이해": "이해,납득,양해",
    "부탁": "당부,부탁,요청,청하다,요구",
    "걱정": "걱정,근심,상심,시름,염려,우수,괴롭다",
    "없다": "없다,비다",
    "천천히": "지각,지체,늦다,굼뜨다,느리다,더디다,천천하다,서서히",
    "모두": "모두,온통,전부,전체,제반,모든,온,다,모조리,몽땅,죄다",
    "가능하다": "가능,할 수 있다",
    "위해": "위하다,-러",
    "당연": "당연하다,마땅하다,응당하다",
    "더": "더,게다가,더구나,추가,더욱,더군다나",
    "정확히": "명확하다,정확,똑똑하다,뚜렷하다,명료하다,명백하다,분명하다,선명하다,확실하다,단연,역력하다,장장하다,틀림없이",
    "이야기": "이야기,강의,설교",
    "약속": "꼭,약속,-야,필수,필시",
    "감사": "감사합니다,감사,고맙다",
    "안": "속,내부,안쪽,안",
    "때": "더럽다,때,불결,지저분하다",
    "글씨": "서예,붓글씨,붓글",
    "쓰다": "이론,쓰다",
    "보여주다": "보여주다",
    "괜찮다": "괜찮다,무방하다",
    "생각": "생각,견해,사고,신경,의견,의사,의식,여기다",
    "스마트폰": "휴대전화,핸드폰,휴대폰,휴대전화기",
    "화면": "백지,용지,종이",
    "적다": "필기,쓰다,적다,쓰기,저술,서술",
    "배려": "양보",
    "감동": "감동",
    "오늘": "오늘,금일,이번,오늘날,현재",
    "날씨": "하늘,개다",
    "맞다": "사실,정말,진짜,참,맞다,정말로",
    "하늘": "하늘,개다",
    "맑다": "결백,깔끔하다,깨끗하다,말끔하다,산뜻하다,소박하다,순결,순수,정결,청결",
    "바람": "바람,바람이 불다,가을,불다",
    "시원": "시원하다,평화,화평",
    "기분": "감정,기분,정서",
    "평소": "평상,평상시,평소",
    "어떤": "어느,무엇,어떤,무슨,뭐,아무,어디",
    "음식": "식당,음식점",
    "가장": "일등,으뜸,제일,최고,가장,맨,수석",
    "좋아하다": "좋다,선",
    "따뜻하다": "남쪽,남,따뜻하다,봄,포근하다",
    "국수": "국수,면",
    "요리": "요리",
    "면": "국수,면",
    "다음": "미래,다음,앞날,앞길,장래,장차,향후",
    "같이": "함께,같이,동반,랑,아울러,더불다,-끼리",
    "먹다": "막다,막히다,먹다",
    "가다": "가다",
    "와": "와,과,하고",
    "꼭": "꼭,약속,-야,필수,필시",
    "맛있다": "맛있다,맛나다,맛",
    "친절": "친절,대우,접대,서비스,대접",
    "대화": "대화,대담",
    "즐겁다": "반갑다,반기다,재미,흥,흥취,희열,즐겁다,즐기다",
    "앞으로": "미래,다음,앞날,앞길,장래,장차,향후",
    "우리": "우리,저희",
    "자주": "반복,거듭,수시로,자꾸,자주,잦다,여러 번,연거푸,재차,빈번히"
}

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
            
        # 대화 전용 동의어 맵 연동
        mapped = DIALOGUE_WORDS_MAP.get(word, word)
            
        # 0. 입력어 자체의 콤마 처리 (복합어인 경우 첫 번째 단어 우선 시도)
        sub_words = [w.strip() for w in mapped.split(",")]
        
        # 1. 정확한 매칭 (입력어 전체 또는 개별 단어)
        search_candidates = [mapped] + sub_words
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
