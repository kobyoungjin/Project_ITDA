"""
'나' 관련 단어 샘플을 늘려서 재학습하는 스크립트
- 프레임 샘플링 간격을 줄여 더 많은 샘플 추출 (기존 3프레임 → 1프레임)
- 단어당 최대 샘플 수도 20→60으로 확대
"""
import os
import cv2
import csv
import urllib.request
from pathlib import Path
import mediapipe as mp
import pandas as pd
from sklearn.neighbors import KNeighborsClassifier
from sklearn.model_selection import cross_val_score
import joblib, sys

sys.path.append(str(Path('.').absolute()))
from api.core.ml_utils import extract_ksl_features

DATA_DIR = Path("api/data/ksl_training")
CSV_PATH = DATA_DIR / "ksl_dataset.csv"
MODEL_PATH = DATA_DIR / "knn_model.pkl"

# 기존 CSV에서 재학습 대상 단어 데이터만 삭제 (신규 데이터로 교체)
REPLACE_LABELS = ['자신,나,저,내', '너,네,자네']

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

def _process_video_file(video_path: str, label: str, max_samples=60):
    mp_hands = mp.solutions.hands
    saved_count = 0
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Failed to open {video_path}")
        return 0

    print(f"  총 프레임: {int(cap.get(cv2.CAP_PROP_FRAME_COUNT))}")
    try:
        with mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.4,  # 더 관대하게 (기존 0.5)
            min_tracking_confidence=0.4
        ) as hands:
            count = 0
            while cap.isOpened() and saved_count < max_samples:
                ret, frame = cap.read()
                if not ret: break

                count += 1
                if count % 2 != 0: continue  # 기존 3프레임 간격 → 2프레임(더 촘촘히)

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
                            if label_side == "Right":
                                right_lms = lms
                            else:
                                left_lms = lms

                    features = extract_ksl_features(right_lms, left_lms)
                    if features:
                        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
                            writer = csv.writer(f)
                            writer.writerow(features + [label])
                        saved_count += 1
    finally:
        cap.release()
    return saved_count


# ── 1. 기존 CSV에서 재학습 대상 단어 행 삭제 ────────────────────────
print("기존 CSV에서 재학습 대상 데이터 삭제 중...")
if CSV_PATH.exists():
    df_old = pd.read_csv(CSV_PATH, encoding='utf-8')
    before = len(df_old)
    df_old = df_old[~df_old['label'].isin(REPLACE_LABELS)]
    df_old.to_csv(CSV_PATH, index=False, encoding='utf-8')
    print(f"  삭제 완료: {before} → {len(df_old)} 행")

# ── 2. 영상 재다운로드 & 샘플 추출 ──────────────────────────────────
for t in targets:
    print(f"\n[처리 중] {t['label']}")
    temp_path = f"temp_dl_{t['label'][:2]}.mp4"
    print(f"  다운로드 중...")
    urllib.request.urlretrieve(t['url'], temp_path)
    cnt = _process_video_file(temp_path, t['label'], max_samples=60)
    print(f"  저장된 샘플: {cnt}개")
    if os.path.exists(temp_path):
        os.remove(temp_path)

# ── 3. 전체 데이터 정제 & 모델 재훈련 ───────────────────────────────
print("\nKNN 모델 재훈련 중...")
df = pd.read_csv(CSV_PATH, encoding='utf-8')
df = df.drop_duplicates()
df = df.groupby('label').head(100).reset_index(drop=True)
df.to_csv(CSV_PATH, index=False, encoding='utf-8')

# 레이블별 샘플 수 출력
print("\n=== 레이블별 샘플 수 ===")
counts = df['label'].value_counts()
for lbl in REPLACE_LABELS:
    print(f"  {lbl}: {counts.get(lbl, 0)}개")

X = df.drop("label", axis=1).values
y = df["label"].values
labels = sorted(set(y))

model = KNeighborsClassifier(n_neighbors=5, metric="euclidean", weights="distance")

# 교차 검증
if len(df) >= 20:
    scores = cross_val_score(model, X, y, cv=min(5, len(labels)), scoring="accuracy")
    print(f"\n교차 검증 정확도: {scores.mean()*100:.1f}%")

model.fit(X, y)
joblib.dump(model, MODEL_PATH)
print(f"\n✅ 재훈련 완료! 총 {len(labels)}개 단어, {len(df)}개 샘플")
print("백엔드 서버가 자동으로 새 모델을 반영합니다.")
