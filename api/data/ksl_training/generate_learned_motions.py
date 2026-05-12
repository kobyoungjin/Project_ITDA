import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

import json
from api.services.motion_extractor import motion_extractor

def generate_motions(limit=50):
    urls_path = Path("api/data/sign_video_urls.json")
    with open(urls_path, "r", encoding="utf-8") as f:
        urls_data = json.load(f)
    
    items = list(urls_data.items())[:limit]
    success_count = 0
    
    print(f"Generating motion data for {limit} words...")
    for i, (label, info) in enumerate(items):
        print(f"[{i+1}/{limit}] Processing '{label}'...", end="", flush=True)
        # Check if already exists
        target_path = Path("frontend/data/ksl_motions") / f"{label}.json"
        if target_path.exists():
            print(" Already exists.")
            success_count += 1
            continue
            
        success = motion_extractor.extract_and_save(label)
        if success:
            print(" Success!")
            success_count += 1
        else:
            print(" Failed.")
            
    print(f"\nDone! Generated {success_count}/{limit} motions.")

if __name__ == "__main__":
    generate_motions(50)
