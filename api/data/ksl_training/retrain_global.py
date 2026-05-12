import json, os, sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from api.routers.collect import collect_from_url, train_knn_model
import anyio

async def main():
    print("Starting Global Retraining with new normalization...")
    # 1. Clear old CSV
    csv_path = Path("api/data/ksl_training/ksl_dataset.csv")
    if csv_path.exists():
        os.remove(csv_path)
    
    # 2. Load top 50 words
    urls_path = Path("api/data/sign_video_urls.json")
    with open(urls_path, "r", encoding="utf-8") as f:
        urls_data = json.load(f)
    
    items = list(urls_data.items())[:50]
    
    for i, (label, info) in enumerate(items):
        url = info.get("video_url")
        if not url: continue
        print(f"[{i+1}/50] Processing '{label}'...")
        try:
            await collect_from_url(label, url)
        except Exception as e:
            print(f"  Error: {e}")
            
    # 3. Train
    print("\nTraining KNN model...")
    res = train_knn_model(n_neighbors=5)
    print(f"Training Complete: {res}")

if __name__ == "__main__":
    anyio.run(main)
