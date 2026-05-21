import sys
from pathlib import Path
import tempfile
import requests
import json

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.services.motion_extractor import motion_extractor
from api.tools.mediapipe_retarget import extract_from_video, save_motion_json
import pandas as pd

def get_needed_words():
    words_set = set()
    for csv_name in ['ksl_dataset.csv', 'ksl_dataset_dialogue.csv']:
        csv_path = ROOT / 'api/data/ksl_training' / csv_name
        if not csv_path.exists():
            continue
        df = pd.read_csv(csv_path, encoding='utf-8')
        for word in df['label'].unique():
            words_set.add(word)
            
    # Check which ones need V3 JSON
    needs_v3 = []
    motion_dir = ROOT / 'frontend/data/ksl_motions'
    for word in sorted(list(words_set)):
        f = motion_dir / f'{word}.json'
        if not f.exists():
            needs_v3.append(word)
            continue
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            # If it has frames but not keyframes, it's old format (needs V3 extraction)
            if not data.get('keyframes'):
                needs_v3.append(word)
        except:
            needs_v3.append(word)
            
    return needs_v3

def main():
    needs_v3 = get_needed_words()
    print(f"총 {len(needs_v3)}개의 단어에 대해 V3 모션 데이터 추출이 필요합니다.")
    print("대상 단어:", needs_v3)
    
    success_count = 0
    fail_count = 0
    
    for idx, word in enumerate(needs_v3, 1):
        print(f"\n[{idx}/{len(needs_v3)}] '{word}' 추출 시작...")
        
        # 1. 영상 URL 조회
        video_url = motion_extractor.find_video_url(word)
        if not video_url:
            print(f"  > [실패] '{word}'의 영상 URL을 찾을 수 없습니다.")
            fail_count += 1
            continue
            
        video_url = video_url.replace("http://", "https://")
        
        # 2. 영상 다운로드
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            
        try:
            print(f"  > 다운로드 중: {video_url}")
            resp = requests.get(video_url, timeout=30)
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                f.write(resp.content)
                
            # 3. V3 모션 데이터 추출 (quaternion keyframes)
            # min_delta_rad=0.05 로 설정하여 적절한 압축
            print(f"  > MediaPipe V3 리타게팅 추출 진행...")
            motion = extract_from_video(tmp_path, word, min_delta_rad=0.05)
            
            # 4. 저장
            output_dir = ROOT / 'frontend' / 'data' / 'ksl_motions'
            save_motion_json(motion, output_dir)
            
            print(f"  > [성공] '{word}' 추출 완료 및 저장 성공!")
            success_count += 1
            
        except Exception as e:
            print(f"  > [실패] '{word}' 추출 중 에러 발생: {e}")
            fail_count += 1
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
                
    print(f"\n전체 처리 완료! 성공: {success_count}, 실패: {fail_count}")

if __name__ == '__main__':
    main()
