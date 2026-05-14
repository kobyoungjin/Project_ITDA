import glob
import os

def combine():
    files = sorted(glob.glob("*2026.05.*.md"))
    combined_content = "# [ITDA] 한국 수어 인식 프로젝트 개발 진행서 (통합본)\n\n"
    
    for f in files:
        date = f.split(".md")[0].split(" ")[-1]
        content = open(f, "r", encoding="utf-8").read()
        combined_content += f"## 📅 진행 날짜: {date}\n\n"
        combined_content += content + "\n\n---\n\n"
    
    # 오늘 날짜 분량 추가
    today_content = """# 📅 진행 날짜: 2026.05.14

### ✅ 핵심 업데이트: 인식 엔진 고도화 및 안정성 강화
오늘은 KSL 인식의 '정확도'와 '구분력'을 실사용 수준으로 끌어올리기 위한 전면적인 엔진 업그레이드를 진행했습니다.

#### 1. 시계열 모션 특징(Velocity) 도입 (76차원 확장)
- **궤적 분석**: 단순히 손 모양만 보는 것이 아니라, 손이 움직이는 방향(dx, dy, dz)을 계산하여 '가다/오다' 같은 반대 동작을 완벽히 구분하도록 개선했습니다.
- **공간 감도 극대화**: 코(Nose) 기준의 Y축(높이)과 X축(좌우) 가중치를 3배로 높여 '나/너'(가슴)와 '맛있다/좋다'(얼굴)의 혼동을 해결했습니다.

#### 2. 데이터셋 품질 혁신 (Data Trimming)
- **자동 자르기 로직**: 사전 영상 학습 시 앞뒤의 불필요한 '정지 프레임'을 20~35% 제거하여 순수 동작 데이터만 추출합니다.
- **'친구' 도배 해결**: 오인식이 많았던 '친구' 단어의 추출 구간을 더 엄격하게 제한하여 시스템 전체의 안정성을 확보했습니다.

#### 3. 장애 조치 및 성능 최적화
- **Gemini API 예외 처리**: 403 인증 에러 발생 시 10분간 자동 차단 및 로컬 엔진(Ollama/Rule-based)으로 즉시 전환하는 서킷 브레이커를 구현했습니다.
- **GPU 가속 및 60fps 지원**: MediaPipe 설정을 최적화하여 저사양 환경에서도 실시간 인식이 가능하도록 성능을 튜닝했습니다.
- **인식 문턱값 상향 (0.6)**: 60% 이상의 확신이 들 때만 결과를 출력하여 '아무 동작도 안 할 때' 오작동하는 현상을 방지했습니다.

---
"""
    combined_content += today_content
    
    with open("개발진행서_통합.md", "w", encoding="utf-8") as out:
        out.write(combined_content)
    print("Combined report created: 개발진행서_통합.md")

if __name__ == "__main__":
    combine()
