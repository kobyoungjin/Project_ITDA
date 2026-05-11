"""기존 데이터 삭제 후, 증강 파이프라인으로 재학습"""
import os, sys, cv2, csv, urllib.request
from pathlib import Path
import pandas as pd
from sklearn.neighbors import KNeighborsClassifier
from sklearn.model_selection import cross_val_score
import joblib, mediapipe as mp

sys.path.append(str(Path('.').absolute()))
from api.core.ml_utils import extract_ksl_features, augment_landmarks

DATA_DIR = Path("api/data/ksl_training")
CSV_PATH = DATA_DIR / "ksl_dataset.csv"
MODEL_PATH = DATA_DIR / "knn_model.pkl"

REPLACE_LABELS = ['자신,나,저,내', '너,네,자네']
targets = [
    {'label': '자신,나,저,내', 'url': 'https://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191029/632250/MOV000255787_700X466.mp4'},
    {'label': '너,네,자네',   'url': 'https://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191014/627265/MOV000251996_700X466.mp4'},
]

def _save(features, label):
    is_new = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow([f"f{i}" for i in range(len(features))] + ["label"])
        writer.writerow(features + [label])

def process(video_path, label, max_samples=100):
    mp_hands = mp.solutions.hands
    saved = 0
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened(): return 0
    try:
        with mp_hands.Hands(static_image_mode=False, max_num_hands=2,
                            min_detection_confidence=0.5, min_tracking_confidence=0.5) as hands:
            count = 0
            while cap.isOpened() and saved < max_samples:
                ret, frame = cap.read()
                if not ret: break
                count += 1
                if count % 5 != 0: continue
                image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res = hands.process(image)
                if res.multi_hand_landmarks:
                    r_lms = l_lms = None
                    for i, hh in enumerate(res.multi_handedness or []):
                        side = hh.classification[0].label
                        lms = [{"x": lm.x, "y": lm.y, "z": lm.z} for lm in res.multi_hand_landmarks[i].landmark]
                        if side == "Right": r_lms = lms
                        else: l_lms = lms
                    # 원본
                    feats = extract_ksl_features(r_lms, l_lms)
                    if feats:
                        _save(feats, label); saved += 1
                    # 증강 (8배)
                    base = r_lms or l_lms
                    if base:
                        for aug in augment_landmarks(base, n=8):
                            if saved >= max_samples: break
                            aug_r = aug if r_lms else None
                            aug_l = aug if l_lms else None
                            aug_f = extract_ksl_features(aug_r, aug_l)
                            if aug_f:
                                _save(aug_f, label); saved += 1
    finally:
        cap.release()
    return saved

# 기존 대상 단어 삭제
print("기존 데이터 삭제 중...")
df_old = pd.read_csv(CSV_PATH, encoding='utf-8')
before = len(df_old)
df_old = df_old[~df_old['label'].isin(REPLACE_LABELS)]
df_old.to_csv(CSV_PATH, index=False, encoding='utf-8')
print(f"  {before} -> {len(df_old)}행")

# 증강 포함 재수집
for t in targets:
    print(f"[{t['label']}] 다운로드 중...")
    tmp = f"tmp_aug_{t['label'][:2]}.mp4"
    urllib.request.urlretrieve(t['url'], tmp)
    cnt = process(tmp, t['label'])
    print(f"  저장: {cnt}개 (원본+증강)")
    if os.path.exists(tmp): os.remove(tmp)

# 재학습
print("\nKNN 재훈련...")
df = pd.read_csv(CSV_PATH, encoding='utf-8')
df = df.drop_duplicates()
df = df.groupby('label').head(100).reset_index(drop=True)
df.to_csv(CSV_PATH, index=False, encoding='utf-8')

counts = df['label'].value_counts()
for lbl in REPLACE_LABELS:
    print(f"  {lbl}: {counts.get(lbl, 0)}개")

X = df.drop("label", axis=1).values
y = df["label"].values
labels = sorted(set(y))
model = KNeighborsClassifier(n_neighbors=5, metric="euclidean", weights="distance")
if len(df) >= 20:
    scores = cross_val_score(model, X, y, cv=min(5, len(labels)), scoring="accuracy")
    print(f"\n교차검증 정확도: {scores.mean()*100:.1f}%")
model.fit(X, y)
joblib.dump(model, MODEL_PATH)
print(f"완료: {len(labels)}개 단어, {len(df)}개 샘플")
