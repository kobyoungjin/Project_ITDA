import pandas as pd
import numpy as np
import joblib
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix
import os

# 경로 설정
DATA_PATH = Path("api/data/ksl_training/ksl_dataset.csv")
MODEL_PATH = Path("api/data/ksl_training/knn_model.pkl")

def evaluate():
    if not DATA_PATH.exists():
        print(f"[Error] No dataset file found at: {DATA_PATH}")
        return

    print(f"[Evaluate] Loading data: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH, encoding='utf-8')
    
    # 1. 데이터 준비
    X = df.drop("label", axis=1).values
    y = df["label"].values
    
    # 클래스별 샘플 수 확인
    print("\n--- Sample Distribution per Class (Top 10) ---")
    print(df["label"].value_counts().head(10))
    print(f"Total Samples: {len(df)}, Total Classes: {len(np.unique(y))}")

    # 2. Train/Test Split (8:2)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y if len(np.unique(y)) > 1 else None
    )

    # 3. 모델 훈련
    from sklearn.neighbors import KNeighborsClassifier
    model = KNeighborsClassifier(n_neighbors=3, weights='distance')
    model.fit(X_train, y_train)

    # 4. 예측 및 평가
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)

    print("\n==========================================")
    print(f"KNN Model Evaluation Result (Test Set Accuracy: {acc:.2%})")
    print("==========================================\n")
    
    print(classification_report(y_test, y_pred))

    # 샘플 수가 적어 주의가 필요한 단어들
    low_samples = df["label"].value_counts()
    low_samples = low_samples[low_samples < 10]
    if not low_samples.empty:
        print("\n[Warning] Classes with low samples (Needs reinforcement):")
        for label, count in low_samples.items():
            print(f"  - {label}: {count} samples")

if __name__ == "__main__":
    # PYTHONPATH 설정
    os.environ["PYTHONPATH"] = "."
    evaluate()
