"""
KNN 모델 진단 스크립트
- 모델 내 클래스별 샘플 수 확인
- CSV vs 모델 레이블 불일치 검사
- 자기 자신 데이터로 예측 테스트 (최소 정확도 검증)
"""
import sys, joblib, numpy as np, pandas as pd
from pathlib import Path
from sklearn.model_selection import cross_val_score

sys.path.append(str(Path('.').absolute()))

MODEL_PATH = Path("api/data/ksl_training/knn_model.pkl")
CSV_PATH   = Path("api/data/ksl_training/ksl_dataset.csv")

# ── 1. 모델 파일 확인 ───────────────────────────────────────────────
print("=" * 55)
print("[ 1. 모델 파일 상태 ]")
if not MODEL_PATH.exists():
    print("  ERROR: knn_model.pkl 없음!")
    sys.exit(1)

model = joblib.load(MODEL_PATH)
classes = list(model.classes_)
print(f"  총 클래스 수: {len(classes)}")
print(f"  학습된 단어: {classes}")
print(f"  n_neighbors : {model.n_neighbors}")
print(f"  metric      : {model.metric}")

# ── 2. CSV vs 모델 레이블 비교 ────────────────────────────────────
print("\n[ 2. CSV vs 모델 레이블 비교 ]")
if CSV_PATH.exists():
    df = pd.read_csv(CSV_PATH, encoding='utf-8')
    csv_labels = sorted(df['label'].unique())
    model_labels = sorted(classes)
    missing_in_model = [l for l in csv_labels if l not in model_labels]
    missing_in_csv   = [l for l in model_labels if l not in csv_labels]
    print(f"  CSV 레이블 수  : {len(csv_labels)}")
    print(f"  모델 레이블 수 : {len(model_labels)}")
    if missing_in_model:
        print(f"  [!] 모델에 없는 CSV 레이블: {missing_in_model}")
    if missing_in_csv:
        print(f"  [!] CSV에 없는 모델 레이블: {missing_in_csv}")
    if not missing_in_model and not missing_in_csv:
        print("  OK: 레이블 완전 일치")

# ── 3. 클래스별 샘플 수 ───────────────────────────────────────────
print("\n[ 3. 클래스별 샘플 수 (CSV 기준) ]")
counts = df['label'].value_counts().sort_index()
for lbl, cnt in counts.items():
    flag = " <<<< 샘플 부족!" if cnt < 10 else ""
    print(f"  {lbl:30s}: {cnt:3d}개{flag}")

# ── 4. 핵심: 자기 자신 데이터로 예측 테스트 ──────────────────────
print("\n[ 4. 클래스별 자기예측 정확도 (Train-set Self-test) ]")
X = df.drop("label", axis=1).values
y = df["label"].values

for target_label in sorted(set(y)):
    mask = y == target_label
    X_cls = X[mask]
    if len(X_cls) == 0:
        continue
    preds = model.predict(X_cls)
    correct = (preds == target_label).sum()
    acc = correct / len(X_cls) * 100
    flag = " <-- 문제!" if acc < 50 else ""
    print(f"  {target_label:30s}: {acc:5.1f}%  ({correct}/{len(X_cls)}){flag}")

# ── 5. 교차검증 전체 정확도 ──────────────────────────────────────
print("\n[ 5. 전체 교차검증 정확도 (5-fold) ]")
from sklearn.neighbors import KNeighborsClassifier
knn_test = KNeighborsClassifier(n_neighbors=model.n_neighbors, metric=model.metric, weights=model.weights)
n_splits = min(5, len(set(y)))
try:
    scores = cross_val_score(knn_test, X, y, cv=n_splits, scoring="accuracy")
    print(f"  평균: {scores.mean()*100:.1f}%  각: {[f'{s*100:.0f}%' for s in scores]}")
except Exception as e:
    print(f"  교차검증 실패: {e}")

# ── 6. '나' 관련 단어 특이 진단 ─────────────────────────────────
print("\n[ 6. '나' 관련 단어 혼동 분석 ]")
target = '자신,나,저,내'
if target in set(y):
    mask = y == target
    X_cls = X[mask]
    probas = model.predict_proba(X_cls)
    avg_max_conf = probas.max(axis=1).mean()
    top_predictions = [model.classes_[np.argmax(p)] for p in probas]
    from collections import Counter
    pred_counts = Counter(top_predictions)
    print(f"  '{target}' 평균 최고신뢰도: {avg_max_conf:.3f}")
    print(f"  예측 분포: {dict(pred_counts)}")
else:
    print(f"  '{target}' 레이블이 CSV에 없음!")

print("\n진단 완료.")
