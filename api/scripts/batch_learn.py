import cv2
import mediapipe as mp
import pandas as pd
import numpy as np
import os
import json
import requests
from pathlib import Path
from api.core.ml_utils import extract_ksl_features
import joblib
import csv
from sklearn.neighbors import KNeighborsClassifier

# 경로 설정
BASE_DIR = Path("api/data/ksl_training")
CSV_PATH = BASE_DIR / "ksl_dataset.csv"
MODEL_PATH = BASE_DIR / "knn_model.pkl"
URLS_PATH = Path("api/data/sign_video_urls.json")

# MediaPipe 초기화
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(static_image_mode=False, max_num_hands=2, min_detection_confidence=0.5)

# 세션 객체 생성 (쿠키 유지)
session = requests.Session()

import subprocess

def process_video_url(label, url, limit_frames=30):
    """URL에서 비디오 다운로드 후 특징 추출 (curl 사용 버전)"""
    tmp_path = "tmp_video.mp4"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
        
    try:
        # 시스템 curl 명령어로 다운로드 시도
        cmd = [
            "curl", "-L", "-s",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "-H", "Referer: http://sldict.korean.go.kr/",
            "--connect-timeout", "15",
            "--max-time", "60",
            "-o", tmp_path,
            url
        ]
        subprocess.run(cmd, check=True)
    except Exception as e:
        print(f"  [Error] curl 다운로드 실패: {e}")
        return []



    cap = cv2.VideoCapture(tmp_path)
    extracted_features = []
    frame_count = 0

    while cap.isOpened() and frame_count < limit_frames:
        ret, frame = cap.read()
        if not ret:
            break

        # BGR to RGB
        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(image)

        if results.multi_hand_landmarks:
            right_lms = None
            left_lms = None
            
            for i, res in enumerate(results.multi_handedness):
                label_side = res.classification[0].label # "Right" or "Left"
                hlm = results.multi_hand_landmarks[i]
                lms = [{"x": lm.x, "y": lm.y, "z": lm.z} for lm in hlm.landmark]
                
                if label_side == "Right":
                    right_lms = lms
                else:
                    left_lms = lms
            
            features = extract_ksl_features(right_lms, left_lms)
            if features:
                # 영상 URL을 출처(source)로 기록 — 누수 없는 평가용
                extracted_features.append(features + [f"url:{url}", label])
                frame_count += 1

    cap.release()
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    return extracted_features

def batch_learn(limit: int = 50):
    TARGET_SAMPLES = 25  # 단어별 최소 목표 샘플 수
    
    # 1. 기존 데이터셋 분석
    existing_counts = {}
    all_data = []
    if CSV_PATH.exists():
        try:
            df_old = pd.read_csv(CSV_PATH, encoding='utf-8')
            existing_counts = df_old['label'].value_counts().to_dict()
            all_data = df_old.values.tolist()
            print(f"[Batch] 기존 데이터셋 로드됨. 총 {len(df_old)} 샘플.")
        except Exception as e:
            print(f"[Batch] 데이터셋 로드 실패: {e}")

    # 2. 사전 데이터 로드
    if not URLS_PATH.exists():
        print(f"[Error] {URLS_PATH}이 없습니다.")
        return
    with open(URLS_PATH, "r", encoding="utf-8") as f:
        urls = json.load(f)

    labels = list(urls.keys())[:limit]
    print(f"[Batch] {len(labels)}개 단어에 대해 지능적 수집 시작 (Target: {TARGET_SAMPLES})")

    # 3. 선별적 특징 추출
    new_samples_added = False
    for i, label in enumerate(labels):
        current_count = existing_counts.get(label, 0)
        
        # 이미 충분하면 건너뜀
        if current_count >= TARGET_SAMPLES:
            print(f"  - {i+1}/{len(labels)} [{label}] 이미 충분함 ({current_count}개) - 건너뜀")
            continue
            
        print(f"  - {i+1}/{len(labels)} [{label}] 수집 시작 (현재: {current_count}개)...")
        v_url = urls[label].get("video_url")
        if not v_url: continue

        # 부족한 만큼만 더 추출
        new_features = process_video_url(label, v_url, limit_frames=TARGET_SAMPLES - current_count)
        if new_features:
            all_data.extend(new_features)
            new_samples_added = True
            print(f"    -> {len(new_features)}개 샘플 추가됨.")
        
        # [과제 5] 서버 부하 방지 및 차단 회피를 위한 지연 시간
        import time
        time.sleep(3)


    if not all_data:
        print("[Batch] 학습할 데이터가 없습니다.")
        return

    # 4. 데이터 저장 및 균형 조정 (다운샘플링)
    # 컬럼명 생성 (f0, f1, ... , source, label)
    feat_dim = len(all_data[0]) - 2
    columns = [f"f{i}" for i in range(feat_dim)] + ["source", "label"]
    df_total = pd.DataFrame(all_data, columns=columns)
    
    balanced_groups = []
    for l in df_total['label'].unique():
        group = df_total[df_total['label'] == l]
        if len(group) > 50:
            group = group.sample(n=50, random_state=42)
        balanced_groups.append(group)
    
    df_final = pd.concat(balanced_groups, ignore_index=True)
    df_final.to_csv(CSV_PATH, index=False, encoding='utf-8')
    print(f"[Batch] 저장 완료! 최종 데이터셋 크기: {len(df_final)} 샘플")
    
    # 5. 모델 훈련
    train_knn_model()

def train_knn_model():
    if not CSV_PATH.exists():
        return
    
    print("\n[Train] KNN 모델 훈련 시작...")
    df = pd.read_csv(CSV_PATH, encoding='utf-8')
    # source 는 출처 메타데이터이므로 학습 특징에서 제외
    X = df.drop(columns=["label", "source"], errors="ignore").values
    y = df["label"].values
    
    model = KNeighborsClassifier(n_neighbors=3, weights='distance')
    model.fit(X, y)
    
    joblib.dump(model, MODEL_PATH)
    print(f"[Success] 모델 저장 완료: {MODEL_PATH}")
    print(f"   - 학습된 단어 수: {len(np.unique(y))}")
    print(f"   - 총 샘플 수: {len(y)}")

if __name__ == "__main__":
    batch_learn(limit=50)
