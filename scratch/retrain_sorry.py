import os
import sys
import anyio
import pandas as pd
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from api.routers.collect import collect_from_url, train_knn_model

CSV_PATH = Path("api/data/ksl_training/ksl_dataset.csv")

async def main():
    print("[ITDA Retrain] Sorry re-training script started.")
    
    # 1. Clean old "미안" or "미안하다" from CSV
    if CSV_PATH.exists():
        df = pd.read_csv(CSV_PATH, encoding='utf-8')
        original_len = len(df)
        df_filtered = df[~df['label'].isin(['미안', '미안하다'])]
        new_len = len(df_filtered)
        
        if new_len < original_len:
            df_filtered.to_csv(CSV_PATH, index=False, encoding='utf-8')
            print(f"Removed {original_len - new_len} old '미안'/'미안하다' samples from CSV.")
        else:
            print("No old '미안' or '미안하다' samples found in CSV.")
    else:
        print("CSV dataset does not exist. It will be created.")

    # 2. Extract from dictionary video URL for "죄송하다,사과,미안하다"
    # URL: http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191022/630183/MOV000253802_700X466.mp4
    url = "http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191022/630183/MOV000253802_700X466.mp4"
    label = "미안하다"
    
    print(f"Extracting samples for '{label}' from {url}...")
    res = await collect_from_url(label, url)
    if res.get("ok"):
        print(f"Extraction successful: {res.get('saved_samples')} samples.")
    else:
        print(f"Extraction failed: {res.get('message')}")
        return

    # 3. Train KNN model
    print("Training KNN model with the new dataset...")
    train_res = train_knn_model(n_neighbors=5)
    if train_res.get("ok"):
        print(f"Training successful! Classes: {train_res.get('labels')}")
        print(f"Accuracy: {train_res.get('accuracy')}%")
    else:
        print(f"Training failed: {train_res.get('message')}")

if __name__ == "__main__":
    anyio.run(main)
