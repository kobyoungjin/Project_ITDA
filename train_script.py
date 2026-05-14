"""
20개 일상어 KNN 재학습 스크립트 (백엔드 API 경유)
- 백엔드 서버(localhost:8000)를 통해 각 단어의 영상을 수집하고 학습합니다.
- 실행 전 백엔드 서버가 실행 중이어야 합니다: start_backend.bat
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import urllib.parse
import urllib.request
import json
import time

BASE_URL = 'http://localhost:8000/api/collect'

# ── 20개 일상생활 단어 ──
targets = [
    {'label': '나',       'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191029/632250/MOV000255787_700X466.mp4'},
    {'label': '너',       'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191014/627265/MOV000251996_700X466.mp4'},
    {'label': '안녕',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20200821/733655/MOV000256297_700X466.mp4'},
    {'label': '미안',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20200824/735049/MOV000251405_700X466.mp4'},
    {'label': '사랑',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191021/629620/MOV000253928_700X466.mp4'},
    {'label': '친구',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191015/627705/MOV000257451_700X466.mp4'},
    {'label': '집',       'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191021/629673/MOV000258856_700X466.mp4'},
    {'label': '이름',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191015/627715/MOV000256668_700X466.mp4'},
    {'label': '오늘',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191016/628278/MOV000256336_700X466.mp4'},
    {'label': '내일',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191014/627261/MOV000251976_700X466.mp4'},
    {'label': '가다',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191028/632050/MOV000249486_700X466.mp4'},
    {'label': '오다',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191016/628281/MOV000256338_700X466.mp4'},
    {'label': '먹다',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20200824/735123/MOV000241825_700X466.mp4'},
    {'label': '마시다',   'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20200824/734844/MOV000251932_700X466.mp4'},
    {'label': '알다',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191011/626557/MOV000256441_700X466.mp4'},
    {'label': '있다',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191022/629937/MOV000255212_700X466.mp4'},
    {'label': '좋다',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20200825/735452/MOV000235717_700X466.mp4'},
    {'label': '배고프다', 'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191017/628481/MOV000248310_700X466.mp4'},
    {'label': '맛있다',   'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191014/627269/MOV000252525_700X466.mp4'},
    {'label': '감사',     'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191028/632085/MOV000243986_700X466.mp4'},
]


def call_api(url, method='POST', data=None):
    headers = {'Content-Type': 'application/json'} if data else {}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {'ok': False, 'error': e.read().decode()}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ── 0단계: 백엔드 서버 연결 확인 ──
print("=" * 60)
print("  20개 일상어 KNN 재학습 (백엔드 API 경유)")
print("=" * 60)
print()
print("[0단계] 백엔드 서버 연결 확인...")
try:
    urllib.request.urlopen('http://localhost:8000/api/collect/status', timeout=5)
    print("  [OK] 백엔드 서버 연결 성공")
except Exception as e:
    print(f"  [오류] 백엔드 서버 연결 실패: {e}")
    print("  -> start_backend.bat 으로 서버를 먼저 실행하세요!")
    import sys; sys.exit(1)

# ── 1단계: 기존 CSV 초기화 ──
print()
print("[1단계] 기존 CSV 초기화 중...")
import pandas as pd
from pathlib import Path

CSV_PATH = Path("api/data/ksl_training/ksl_dataset.csv")
if CSV_PATH.exists():
    existing_df = pd.read_csv(CSV_PATH, encoding='utf-8', nrows=1)
    cols = existing_df.columns.tolist()
    pd.DataFrame(columns=cols).to_csv(CSV_PATH, index=False, encoding='utf-8')
    print(f"  ✅ 기존 CSV 초기화 완료 (컬럼 수: {len(cols)})")
else:
    print("  CSV 파일 없음 - 새로 생성 예정")

# ── 2단계: 각 단어 영상 수집 ──
print()
print("[2단계] 영상 수집 중 (백엔드 → 외부 서버)...")
print()

results = []
total_samples = 0

for i, t in enumerate(targets, 1):
    label = t['label']
    url = t['url']
    
    api_url = f"{BASE_URL}/url?label={urllib.parse.quote(label)}&url={urllib.parse.quote(url)}"
    print(f"  [{i:02d}/20] {label} 수집 중...", end='', flush=True)
    
    res = call_api(api_url)
    if res.get('ok'):
        cnt = res.get('saved_samples', 0)
        total_samples += cnt
        results.append(f"{label}: {cnt}개")
        print(f" -> {cnt}개 샘플")
    else:
        err = res.get('message') or res.get('error', '알 수 없는 오류')
        print(f" -> [실패] {err}")
        results.append(f"{label}: 실패")
    
    time.sleep(0.5)  # 서버 부하 방지

print()
print(f"  수집 완료: {total_samples}개 샘플")

# ── 3단계: KNN 학습 ──
print()
print("[3단계] KNN 모델 학습 요청 중...")
train_res = call_api(f"{BASE_URL}/train", data={"n_neighbors": 5})

print()
print("=" * 60)
if train_res.get('ok'):
    print(f"  [완료] 학습 성공!")
    print(f"  - 샘플 수  : {train_res.get('samples')}개")
    print(f"  - 단어 수  : {train_res.get('label_count')}개")
    print(f"  - 정확도   : {train_res.get('accuracy')}%")
    print(f"  - 단어 목록: {', '.join(train_res.get('labels', []))}")
else:
    print(f"  [실패] 학습 오류: {train_res.get('message') or train_res.get('error')}")
print("=" * 60)

print()
print("[수집 결과]")
for r in results:
    print(f"  {r}")
