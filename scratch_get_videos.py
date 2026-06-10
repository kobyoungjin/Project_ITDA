import sys
import os

# add workspace root to path
sys.path.append(r"c:\Users\ComHolic\Documents\GitHub\Project_ITDA_backup")
from api.services.supabase_service import supabase_service

videos = supabase_service.get_all_video_urls()
words = list(videos.keys())

# Create artifact directory
app_data_dir = r"C:\Users\ComHolic\.gemini\antigravity\brain\b10eca48-0165-4edc-b4e7-ff9f6e3e8e05\artifacts"
os.makedirs(app_data_dir, exist_ok=True)
artifact_path = os.path.join(app_data_dir, "video_words_list.md")

with open(artifact_path, "w", encoding="utf-8") as f:
    f.write("# 수어 영상 지원 단어 목록\n\n")
    f.write(f"총 {len(words)}개의 단어가 투명 webm 영상으로 구현되어 있습니다.\n\n")
    f.write("```\n")
    f.write(", ".join(words))
    f.write("\n```\n")

print(f"Total words: {len(words)}")
