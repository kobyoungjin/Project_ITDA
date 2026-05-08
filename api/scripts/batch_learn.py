import os
import cv2
import json
import csv
import requests
import tempfile
import mediapipe as mp
from pathlib import Path
import pandas as pd
import joblib
from sklearn.neighbors import KNeighborsClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from api.core.ml_utils import extract_ksl_features

# MediaPipe 초기화
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(static_image_mode=False, max_num_hands=2, min_detection_confidence=0.5)

DATA_DIR = Path("api/data/ksl_training")
CSV_PATH = DATA_DIR / "ksl_dataset.csv"
URLS_PATH = Path("api/data/sign_video_urls.json")
MODEL_PATH = DATA_DIR / "knn_model.pkl"

def process_video_url(label: str, url: str, limit_frames: int = 20):
    """
    URL에서 영상을 다운로드하여 특징점을 추출하고 CSV에 저장합니다.
    """
    # sldict.korean.go.kr은 http 접속이 불안정할 수 있으므로 https로 전환
    if url.startswith("http://sldict.korean.go.kr"):
        url = url.replace("http://", "https://")

    # 임시 파일로 영상 다운로드
    try:
        print(f"  - 다운로드 중...", end="", flush=True)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f" 실패 (상태 코드: {response.status_code})")
            return 0
        print(" 완료")
    except Exception as e:
        print(f" 에러: {e}")
        return 0

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(response.content)
        tmp_path = tmp.name

    cap = cv2.VideoCapture(tmp_path)
    count = 0
    saved_count = 0
    
    while cap.isOpened() and saved_count < limit_frames:
        ret, frame = cap.read()
        if not ret:
            break
        
        count += 1
        if count % 5 != 0: # 5프레임마다 1개씩 샘플링 (중복 방지)
            continue

        # BGR to RGB
        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(image)

        if results.multi_hand_landmarks:
            right_lms = None
            left_lms = None

            # 각 손의 위치(handedness) 파악
            for idx, hand_handedness in enumerate(results.multi_handedness):
                # MediaPipe의 label은 이미지 기준이므로 실제와 반대일 수 있으나,
                # 일관성 있게 'Right', 'Left'로 분류
                label_side = hand_handedness.classification[0].label
                hlm = results.multi_hand_landmarks[idx]
                lms = [{"x": lm.x, "y": lm.y, "z": lm.z} for lm in hlm.landmark]
                
                if label_side == "Right":
                    right_lms = lms
                else:
                    left_lms = lms
            
            # 양손 정보를 ml_utils에 전달
            features = extract_ksl_features(right_lms, left_lms)
            if features:
                save_to_csv(features, label)
                saved_count += 1

    cap.release()
    os.remove(tmp_path)
    print(f"  - {saved_count}개 샘플 추출 완료")
    return saved_count

def save_to_csv(features, label):
    is_new = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            header = [f"f{i}" for i in range(len(features))] + ["label"]
            writer.writerow(header)
        writer.writerow(features + [label])

def batch_learn(limit_words: int = 10, frames_per_word: int = 10):
    if not URLS_PATH.exists():
        print("Error: sign_video_urls.json 파일을 찾을 수 없습니다.")
        return

    with open(URLS_PATH, "r", encoding="utf-8") as f:
        urls_data = json.load(f)

    total_saved = 0
    words_processed = 0
    
    for label, info in urls_data.items():
        if words_processed >= limit_words:
            break
        
        url = info.get("video_url")
        if not url:
            continue
            
        saved = process_video_url(label, url, limit_frames=frames_per_word)
        if saved > 0:
            total_saved += saved
            words_processed += 1

    print(f"\n[Batch] 완료! 총 {words_processed}개 단어에서 {total_saved}개 샘플을 추출했습니다.")

def train_knn_model():
    print("\n[Train] 모델 훈련 시작...")
    if not CSV_PATH.exists():
        print("Error: 학습 데이터셋(CSV)이 없습니다.")
        return

    df = pd.read_csv(CSV_PATH, encoding='utf-8')
    if len(df) < 5:
        print("Error: 데이터가 너무 적어 훈련할 수 없습니다. (최소 5개 필요)")
        return

    X = df.drop("label", axis=1)
    y = df["label"]

    # 라벨 인코딩 (필요 시)
    model = KNeighborsClassifier(n_neighbors=min(5, len(df)))
    model.fit(X, y)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print(f"[Success] model saved: {MODEL_PATH}")
    print(f"   - labels: {len(model.classes_)}")
    print(f"   - samples: {len(df)}")

if __name__ == "__main__":
    # 상위 10개 단어 학습 진행
    # 상위 50개 단어 학습 진행 (사용자 요청으로 확장)
    batch_learn(limit_words=50, frames_per_word=15)
    
    # 훈련 시작
    train_knn_model()
