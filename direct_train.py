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
import sys

sys.path.append(str(Path('.').absolute()))
from api.core.ml_utils import extract_ksl_features

DATA_DIR = Path("api/data/ksl_training")
CSV_PATH = DATA_DIR / "ksl_dataset.csv"
MODEL_PATH = DATA_DIR / "knn_model.pkl"

# ── 20개 일상생활 단어 (레이블은 대표 단어로 단순화) ──
targets = [
    {'label': '나',      'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191029/632250/MOV000255787_700X466.mp4'},
    {'label': '너',      'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191014/627265/MOV000251996_700X466.mp4'},
    {'label': '안녕',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20200821/733655/MOV000256297_700X466.mp4'},
    {'label': '미안',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20200824/735049/MOV000251405_700X466.mp4'},
    {'label': '사랑',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191021/629620/MOV000253928_700X466.mp4'},
    {'label': '친구',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191015/627705/MOV000257451_700X466.mp4'},
    {'label': '집',      'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191021/629673/MOV000258856_700X466.mp4'},
    {'label': '이름',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191015/627715/MOV000256668_700X466.mp4'},
    {'label': '오늘',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191016/628278/MOV000256336_700X466.mp4'},
    {'label': '내일',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191014/627261/MOV000251976_700X466.mp4'},
    {'label': '가다',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191028/632050/MOV000249486_700X466.mp4'},
    {'label': '오다',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191016/628281/MOV000256338_700X466.mp4'},
    {'label': '먹다',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20200824/735123/MOV000241825_700X466.mp4'},
    {'label': '마시다',  'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20200824/734844/MOV000251932_700X466.mp4'},
    {'label': '알다',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191011/626557/MOV000256441_700X466.mp4'},
    {'label': '있다',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191022/629937/MOV000255212_700X466.mp4'},
    {'label': '좋다',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20200825/735452/MOV000235717_700X466.mp4'},
    {'label': '배고프다','url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191017/628481/MOV000248310_700X466.mp4'},
    {'label': '맛있다',  'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191014/627269/MOV000252525_700X466.mp4'},
    {'label': '감사',    'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191028/632085/MOV000243986_700X466.mp4'},
]

SAMPLES_PER_WORD = 50  # 단어당 최대 샘플 수


def _process_video_file(video_path: str, label: str, max_samples: int = SAMPLES_PER_WORD):
    mp_hands = mp.solutions.hands
    saved_count = 0
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"  [오류] 영상 열기 실패: {video_path}")
        return 0

    try:
        with mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.4,
            min_tracking_confidence=0.4
        ) as hands:
            frame_count = 0
            while cap.isOpened() and saved_count < max_samples:
                ret, frame = cap.read()
                if not ret:
                    break

                frame_count += 1
                if frame_count % 2 != 0:  # 2프레임마다 1개 추출
                    continue

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


# ── 1단계: CSV 초기화 (헤더만 유지) ──
print("=" * 60)
print("  20개 일상어 KNN 재학습 시작")
print("=" * 60)
print()
print("[1단계] 기존 데이터셋 초기화 중...")

# 기존 CSV에서 컬럼 수 확인 후 초기화
if CSV_PATH.exists():
    existing_df = pd.read_csv(CSV_PATH, encoding='utf-8', nrows=1)
    cols = existing_df.columns.tolist()
    pd.DataFrame(columns=cols).to_csv(CSV_PATH, index=False, encoding='utf-8')
    print(f"  기존 CSV 초기화 완료 (컬럼 수: {len(cols)})")
else:
    print("  CSV 파일 없음 - 새로 생성됩니다")

print()
print("[2단계] 영상 다운로드 및 특징 추출 중...")
print()

# ── 2단계: 각 단어 영상 처리 ──
total_samples = 0
for i, t in enumerate(targets, 1):
    label = t['label']
    url = t['url']
    temp_path = f"temp_train_{i:02d}.mp4"

    print(f"  [{i:02d}/20] {label} 처리 중...")
    try:
        urllib.request.urlretrieve(url, temp_path)
        cnt = _process_video_file(temp_path, label)
        total_samples += cnt
        print(f"         → {cnt}개 샘플 저장 완료")
    except Exception as e:
        print(f"         → [오류] {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

print()
print(f"  전체 추출 샘플 수: {total_samples}개")

# ── 3단계: KNN 학습 ──
print()
print("[3단계] KNN 모델 학습 중...")

df = pd.read_csv(CSV_PATH, encoding='utf-8')
df = df.drop_duplicates()

label_counts = df['label'].value_counts()
print(f"  레이블별 샘플 수:")
for lbl, cnt in label_counts.items():
    print(f"    {lbl}: {cnt}개")

# 레이블당 최대 100개로 균형 맞추기
df = df.groupby('label').head(100).reset_index(drop=True)
df.to_csv(CSV_PATH, index=False, encoding='utf-8')

X = df.drop("label", axis=1).values
y = df["label"].values
labels = sorted(set(y))

print(f"\n  학습 데이터: {len(X)}개 샘플, {len(labels)}개 클래스")

model = KNeighborsClassifier(n_neighbors=5, metric="euclidean", weights="distance")
model.fit(X, y)

# 교차 검증
if len(X) >= 10:
    scores = cross_val_score(model, X, y, cv=min(5, len(labels)), scoring='accuracy')
    print(f"  교차 검증 정확도: {scores.mean():.2%} (±{scores.std():.2%})")

joblib.dump(model, MODEL_PATH)

print()
print("=" * 60)
print(f"  ✅ 학습 완료! 모델 저장: {MODEL_PATH}")
print(f"  학습된 단어 ({len(labels)}개): {', '.join(labels)}")
print("=" * 60)
