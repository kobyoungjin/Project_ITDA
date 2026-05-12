"""
'사랑합니다'가 오분류되는 원인 진단
- '사랑합니다' 학습 데이터 확인
- '자신,나,저,내' 데이터와 유사도 비교
- 두 클래스의 평균 특징 벡터 거리 측정
"""
import sys, joblib, numpy as np, pandas as pd
from pathlib import Path
from collections import Counter

sys.path.append(str(Path('.').absolute()))

MODEL_PATH = Path("api/data/ksl_training/knn_model.pkl")
CSV_PATH   = Path("api/data/ksl_training/ksl_dataset.csv")

model = joblib.load(MODEL_PATH)
df = pd.read_csv(CSV_PATH, encoding='utf-8')
X = df.drop("label", axis=1).values
y = df["label"].values

# ── 1. 사랑합니다 샘플로 예측 테스트 ──────────────────────────────
target_a = '사랑합니다,사랑'
# 레이블에 사랑합니다가 포함된 것 찾기
sarang_labels = [l for l in model.classes_ if '사랑' in l]
na_labels = [l for l in model.classes_ if '자신' in l or '나,저' in l]

print(f"'사랑' 포함 레이블: {sarang_labels}")
print(f"'나/자신' 포함 레이블: {na_labels}")

# ── 2. 각 클래스 평균 벡터 비교 ────────────────────────────────────
print("\n=== 클래스별 평균 특징 벡터 (첫 5차원) ===")
for lbl in sarang_labels + na_labels:
    mask = y == lbl
    if mask.sum() == 0: continue
    mean_vec = X[mask].mean(axis=0)
    print(f"  {lbl:25s}: {mean_vec[:5].round(3)}")

# ── 3. '나' 데이터가 어디로 분류되는지 ─────────────────────────────
print("\n=== '자신,나,저,내' 데이터 실제 예측 결과 ===")
for lbl in na_labels:
    mask = y == lbl
    X_cls = X[mask]
    if len(X_cls) == 0: continue
    preds = model.predict(X_cls)
    probas = model.predict_proba(X_cls)
    avg_conf = probas.max(axis=1).mean()
    pred_dist = Counter(preds)
    print(f"  레이블: {lbl} ({len(X_cls)}개)")
    print(f"  예측분포: {dict(pred_dist)}")
    print(f"  평균 최고신뢰도: {avg_conf:.3f}")
    
# ── 4. 두 클래스 간 평균 유클리드 거리 ─────────────────────────────
print("\n=== 클래스 간 평균 거리 ===")
for la in na_labels:
    for lb in sarang_labels:
        ma = y == la
        mb = y == lb
        if ma.sum() == 0 or mb.sum() == 0: continue
        va = X[ma].mean(axis=0)
        vb = X[mb].mean(axis=0)
        dist = np.linalg.norm(va - vb)
        print(f"  '{la}' vs '{lb}': 거리={dist:.4f}")
        
# ── 5. 혼동 행렬: 가장 많이 헷갈리는 클래스 쌍 ────────────────────
print("\n=== 전체 오분류 TOP 10 ===")
preds_all = model.predict(X)
errors = [(y[i], preds_all[i]) for i in range(len(y)) if y[i] != preds_all[i]]
from collections import Counter
print(f"  총 오분류: {len(errors)}개")
for (true, pred), cnt in Counter(errors).most_common(10):
    print(f"  '{true}' -> '{pred}' : {cnt}회")
