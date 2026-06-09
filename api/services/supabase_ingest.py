import os
import sys
import math
import time
import requests
import cv2
import numpy as np
import mediapipe as mp
import xml.etree.ElementTree as ET
from supabase import create_client, Client
from dotenv import load_dotenv

# 터미널 출력 인코딩 설정 (한글 깨짐 방지)
import io
sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding = 'utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding = 'utf-8')

load_dotenv()

class SupabaseIngestMaster:
    def __init__(self):
        self.url = os.environ.get("SUPABASE_URL")
        self.key = os.environ.get("SUPABASE_KEY")
        self.culture_key = os.environ.get("CULTURE_API_KEY")
        self.client: Client = create_client(self.url, self.key)
        self.holistic = mp.solutions.holistic.Holistic(
            model_complexity=2,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

    def vec_normalize(self, v):
        n = np.linalg.norm(v)
        return v / n if n > 1e-6 else v

    def get_quat(self, v_from, v_to):
        v_from, v_to = self.vec_normalize(v_from), self.vec_normalize(v_to)
        dot = np.dot(v_from, v_to)
        if dot > 0.9999: return {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
        if dot < -0.9999:
            axis = np.array([0, 0, 1]) if abs(v_from[2]) < 0.9 else np.array([1, 0, 0])
            axis = self.vec_normalize(np.cross(v_from, axis))
            return {"x": round(axis[0], 5), "y": round(axis[1], 5), "z": round(axis[2], 5), "w": 0.0}
        axis = np.cross(v_from, v_to)
        s = math.sqrt((1 + dot) * 2)
        inv_s = 1.0 / s
        return {"x": round(axis[0] * inv_s, 5), "y": round(axis[1] * inv_s, 5), "z": round(axis[2] * inv_s, 5), "w": round(s * 0.5, 5)}

    def process_frame(self, results, timestamp):
        if not results.pose_world_landmarks: return None
        p = results.pose_world_landmarks.landmark
        lh = results.left_hand_landmarks.landmark if results.left_hand_landmarks else None
        rh = results.right_hand_landmarks.landmark if results.right_hand_landmarks else None
        
        # Z-Up 좌표계 변환 (MediaPipe Y -> Unity/Three.js Z)
        def wpt(i): return np.array([p[i].x, -p[i].z, -p[i].y])
        def hpt(lm): return np.array([lm.x, -lm.z, -lm.y])

        bones = {}
        prefix = "mixamorig:"
        r_sh, l_sh = wpt(12), wpt(11)
        sh_mid = (r_sh + l_sh) / 2
        nose = wpt(0)
        
        # 1. 목/머리 (정면 고정 로직 포함)
        neck_vec = nose - sh_mid
        # 고개가 너무 들리지 않도록 보정
        if neck_vec[1] > 0.1: neck_vec[1] = 0.1
        bones[prefix + "Neck"] = self.get_quat([0, 0, 1], neck_vec)
        
        # 2. 어깨 및 팔 (T-Pose 기준 회전 추출)
        bones[prefix + "RightShoulder"] = {"w": 0.966, "x": 0.259, "y": 0.0, "z": 0.0} # A-Pose 보정
        bones[prefix + "LeftShoulder"] = {"w": 0.966, "x": -0.259, "y": 0.0, "z": 0.0}
        
        bones[prefix + "RightArm"] = self.get_quat([-1, 0, 0], wpt(14) - r_sh)
        bones[prefix + "RightForeArm"] = self.get_quat([-1, 0, 0], wpt(16) - wpt(14))
        bones[prefix + "LeftArm"] = self.get_quat([1, 0, 0], wpt(13) - l_sh)
        bones[prefix + "LeftForeArm"] = self.get_quat([1, 0, 0], wpt(15) - wpt(13))

        # 3. 손가락 (마디별 회전 추출)
        f_map = {
            "Thumb": [0, 1, 2, 3, 4],
            "Index": [0, 5, 6, 7, 8],
            "Middle": [0, 9, 10, 11, 12],
            "Ring": [0, 13, 14, 15, 16],
            "Pinky": [0, 17, 18, 19, 20]
        }
        
        if rh:
            bones[prefix + "RightHand"] = {"w": 0.707, "x": 0.0, "y": 0.707, "z": 0.0}
            for n, ids in f_map.items():
                for j in range(1, 4):
                    v = hpt(rh[ids[j+1]]) - hpt(rh[ids[j]])
                    bones[prefix + f"RightHand{n}{j}"] = self.get_quat([-1, 0, 0], v)
        if lh:
            bones[prefix + "LeftHand"] = {"w": 0.707, "x": 0.0, "y": -0.707, "z": 0.0}
            for n, ids in f_map.items():
                for j in range(1, 4):
                    v = hpt(lh[ids[j+1]]) - hpt(lh[ids[j]])
                    bones[prefix + f"LeftHand{n}{j}"] = self.get_quat([1, 0, 0], v)
                    
        return {"time": round(timestamp, 4), "bones": bones, "morphs": {}}

    def get_video_url(self, word):
        search_word = word.split(",")[0].split("(")[-1].replace(")", "")
        url = "https://api.kcisa.kr/API_CNV_054/request"
        params = {"serviceKey": self.culture_key, "numOfRows": 1, "pageNo": 1, "title": search_word}
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                root = ET.fromstring(res.content)
                item = root.find(".//item")
                if item is not None:
                    v_url = item.find("subDescription").text
                    return v_url.replace("http://", "https://")
        except Exception as e:
            print(f" [오류] URL 조회 실패 ({word}): {e}")
        return None

    def upsert_with_retry(self, word, payload, retries=3):
        for i in range(retries):
            try:
                self.client.table("sign_language_data").upsert(
                    {"word": word, "keypoints_json": [payload]}, 
                    on_conflict="word"
                ).execute()
                return True
            except Exception as e:
                wait = (2 ** i) + (0.1 * i)
                print(f" [재시도] DB 업서트 실패 ({word}), {wait}초 후 재시도... ({e})")
                time.sleep(wait)
        return False

    def ingest_word(self, word):
        v_url = self.get_video_url(word)
        if not v_url:
            print(f" [실패] '{word}' 영상을 찾을 수 없습니다.")
            return False

        print(f" [처리] '{word}' 분석 중... ({v_url})")
        try:
            v_data = requests.get(v_url, timeout=30).content
            temp_file = f"temp_{int(time.time())}.mp4"
            with open(temp_file, 'wb') as f: f.write(v_data)
            
            cap = cv2.VideoCapture(temp_file)
            kfs = []
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret: break
                res = self.holistic.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                f_data = self.process_frame(res, cap.get(cv2.CAP_PROP_POS_MSEC)/1000)
                if f_data: kfs.append(f_data)
            cap.release()
            os.remove(temp_file)

            if not kfs:
                print(f" [실패] '{word}' 추출된 키프레임이 없습니다.")
                return False

            payload = {
                "id": word, 
                "version": "v26.0-master", 
                "space": "world", 
                "source": "culture_api",
                "keyframes": kfs
            }
            
            if self.upsert_with_retry(word, payload):
                print(f" [성공] '{word}' 적재 완료 ({len(kfs)} frames)")
                return True
        except Exception as e:
            print(f" [오류] '{word}' 처리 중 예외 발생: {e}")
        return False

    def run_batch(self, word_list):
        print(f"🚀 총 {len(word_list)}개 단어 배치 인제스션 시작...")
        success_count = 0
        for word in word_list:
            if self.ingest_word(word):
                success_count += 1
        print(f"✅ 배치 처리 완료: {success_count}/{len(word_list)} 성공")

if __name__ == "__main__":
    master = SupabaseIngestMaster()
    # 테스트용 단어 리스트
    test_words = ["감사", "사랑", "두려움"]
    master.run_batch(test_words)
