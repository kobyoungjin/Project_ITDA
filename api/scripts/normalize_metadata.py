import json
from pathlib import Path

# 경로 설정
METADATA_PATH = Path("api/data/metadata.json")

def normalize():
    if not METADATA_PATH.exists():
        print(f"[Error] {METADATA_PATH}가 없습니다.")
        return

    print(f"[Normalize] 데이터 로드 중: {METADATA_PATH}")
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    normalized = {}
    duplicate_count = 0

    for item in data:
        keyword = item.get("keyword", "").strip()
        if not keyword: continue

        # 키워드 분리 (예: "탁자,테이블" -> ["탁자", "테이블"])
        synonyms = [k.strip() for k in keyword.replace("/", ",").split(",")]
        primary_key = synonyms[0]

        if primary_key not in normalized:
            normalized[primary_key] = {
                "keyword": primary_key,
                "synonyms": synonyms[1:],
                "description": item.get("description", ""),
                "emotions": list(set(item.get("emotions", []))),
                "video_url": item.get("video_url", "")
            }
        else:
            # 기존 데이터가 있으면 보완
            duplicate_count += 1
            existing = normalized[primary_key]
            
            # 더 자세한 설명이 있으면 업데이트 (AI Hub... 같은 단순 문구 제외)
            new_desc = item.get("description", "")
            if len(new_desc) > len(existing["description"]) and "AI Hub" not in new_desc:
                existing["description"] = new_desc
            
            # 동의어 추가
            for s in synonyms:
                if s != primary_key and s not in existing["synonyms"]:
                    existing["synonyms"].append(s)
            
            # 감정 통합
            existing["emotions"] = list(set(existing["emotions"] + item.get("emotions", [])))
            
            # 비디오 URL 보관
            if not existing["video_url"] and item.get("video_url"):
                existing["video_url"] = item.get("video_url")

    # 결과물 리스트로 변환
    final_result = list(normalized.values())
    
    print(f"[Result] 정리 완료!")
    print(f"  - 원본 항목 수: {len(data)}")
    print(f"  - 중복 제거 수: {duplicate_count}")
    print(f"  - 최종 유니크 키워드: {len(final_result)}")

    # 파일 저장
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(final_result, f, ensure_ascii=False, indent=2)
    
    print(f"[Success] {METADATA_PATH}가 정규화되었습니다.")

if __name__ == "__main__":
    normalize()
