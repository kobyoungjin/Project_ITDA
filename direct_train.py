import os
import cv2
import csv
import urllib.request
from pathlib import Path
import mediapipe as mp
import pandas as pd
from sklearn.neighbors import KNeighborsClassifier
from sklearn.model_selection import cross_val_score
import joblib

# Need to import ml_utils
import sys
sys.path.append(str(Path('.').absolute()))
from api.core.ml_utils import extract_ksl_features

DATA_DIR = Path("api/data/ksl_training")
CSV_PATH = DATA_DIR / "ksl_dataset.csv"
MODEL_PATH = DATA_DIR / "knn_model.pkl"

targets = [
    {
        'label': '자신,나,저,내',
        'url': 'https://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191029/632250/MOV000255787_700X466.mp4'
    },
    {
        'label': '너,네,자네',
        'url': 'https://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191014/627265/MOV000251996_700X466.mp4'
    }
]

def _process_video_file(video_path: str, label: str):
    mp_hands = mp.solutions.hands
    saved_count = 0
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Failed to open {video_path}")
        return 0

    try:
        with mp_hands.Hands(static_image_mode=False, max_num_hands=2, min_detection_confidence=0.5, min_tracking_confidence=0.5) as hands:
            count = 0
            while cap.isOpened() and saved_count < 30:
                ret, frame = cap.read()
                if not ret: break
                
                count += 1
                if count % 3 != 0: continue
                
                image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = hands.process(image)
                
                if results.multi_hand_landmarks:
                    right_lms = None
                    left_lms = None
                    if results.multi_handedness:
                        for idx, hand_handedness in enumerate(results.multi_handedness):
                            label_side = hand_handedness.classification[0].label
                            hlm = results.multi_hand_landmarks[idx]
                            lms = [{"x": lm.x, "y": lm.y, "z": lm.z} for lm in hlm.landmark]
                            if label_side == "Right": right_lms = lms
                            else: left_lms = lms
                    
                    features = extract_ksl_features(right_lms, left_lms)
                    if features:
                        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
                            writer = csv.writer(f)
                            writer.writerow(features + [label])
                        saved_count += 1
    finally:
        cap.release()
    return saved_count

for t in targets:
    print(f"Processing {t['label']}...")
    temp_path = f"temp_{t['label'][:2]}.mp4"
    urllib.request.urlretrieve(t['url'], temp_path)
    cnt = _process_video_file(temp_path, t['label'])
    print(f"Saved {cnt} samples for {t['label']}")
    if os.path.exists(temp_path):
        os.remove(temp_path)

print("Training model...")
df = pd.read_csv(CSV_PATH, encoding='utf-8')
df = df.drop_duplicates()
df = df.groupby('label').head(100).reset_index(drop=True)
df.to_csv(CSV_PATH, index=False, encoding='utf-8')

X = df.drop("label", axis=1).values
y = df["label"].values
labels = sorted(set(y))

model = KNeighborsClassifier(n_neighbors=5, metric="euclidean", weights="distance")
model.fit(X, y)
joblib.dump(model, MODEL_PATH)

print(f"Training complete! Model labels: {len(labels)}")
