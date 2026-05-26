import json, os, sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from api.routers.collect import collect_from_url, train_knn_model
import anyio

# 20개 핵심 단어와 JSON 내 실제 키 매핑
TARGET_WORDS = {
    "나": "자신,나,저,내",
    "너": "너,네,자네",
    "안녕": "안녕,안부",
    "미안하다": "죄송하다,사과,미안하다",
    "친구": "친구,동무,벗,우인",
    "집": "집,주택,가옥,세대,호,댁",
    "이름": "이름,명,성명,성함",
    "오늘": "오늘,금일,이번,오늘날,현재",
    "내일": "내일,명일",
    "가다": "가다",
    "오다": "오다,도래",
    "알다": "알다",
    "있다": "있다",
    "좋다": "좋다,선",
    "맛있다": "맛있다,맛나다,맛",
    "감사": "감사합니다,감사,고맙다"
}

async def main():
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print("[ITDA] 20 core words auto-retraining started (Enhanced Engine)")
    
    # 1. Clear old CSV
    csv_path = Path("api/data/ksl_training/ksl_dataset.csv")
    if csv_path.exists():
        os.remove(csv_path)
        print(f"Old dataset ({csv_path}) deleted.")
    
    # 2. Load JSON
    urls_path = Path("api/data/sign_video_urls.json")
    with open(urls_path, "r", encoding="utf-8") as f:
        urls_data = json.load(f)
    
    count = 0
    total = len(TARGET_WORDS)
    
    for simple_label, json_key in TARGET_WORDS.items():
        count += 1
        info = urls_data.get(json_key)
        if not info or not info.get("video_url"):
            print(f"[{count}/{total}] Warning: '{simple_label}'(key: {json_key}) not found. Skipping.")
            continue
            
        url = info.get("video_url")
        print(f"[{count}/{total}] Processing '{simple_label}'... ({url})")
        try:
            res = await collect_from_url(simple_label, url)
            if res.get("ok"):
                print(f"  Success: {res.get('saved_samples')} samples.")
            else:
                print(f"  Failed: {res.get('message')}")
        except Exception as e:
            print(f"  Error: {e}")
            
    # 3. Train
    print("\nStarting KNN Model training...")
    res = train_knn_model(n_neighbors=5)
    
    if res.get("ok"):
        print(f"Retraining Complete! Total {res.get('samples')} samples, {res.get('label_count')} words learned.")
        print(f"Estimated Accuracy: {res.get('accuracy')}%")
    else:
        print(f"Training Failed: {res.get('message')}")

if __name__ == "__main__":
    anyio.run(main)
