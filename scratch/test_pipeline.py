import os
import sys

# 프로젝트 루트를 파이썬 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.services.data_pipeline import data_pipeline
from api.services.vector_db import vector_db

print("--- 데이터 파이프라인 테스트 시작 ---")
count = data_pipeline.process_and_store(force_refresh=True)
print(f"처리된 데이터 수: {count}")
print(f"벡터 DB 내 총 벡터 수: {vector_db.index.ntotal}")
print(f"메타데이터 수: {len(vector_db.metadata)}")

# 첫 5개 키워드 출력
print("수집된 키워드 샘플:", [m['keyword'] for m in vector_db.metadata[:5]])

if count > 10:
    print("SUCCESS: 데이터가 정상적으로 확장되었습니다.")
else:
    print("FAILURE: 데이터가 여전히 10개 이하입니다.")
