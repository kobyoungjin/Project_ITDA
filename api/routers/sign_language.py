from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
import subprocess
import shutil
import os
from api.services.supabase_service import supabase_service
from api.services.motion_tokenizer import motion_tokenizer

router = APIRouter()

class TokenizeRequest(BaseModel):
    text: str

@router.get("/supabase/motion/{word}")
async def get_supabase_motion(word: str):
    """Supabase에서 특정 단어의 모션 데이터를 가져옵니다.

    내부적으로 supabase_service.resolve() 가 exact → 동의어 → 콤마 alias → NFC 정규화
    순으로 매핑하므로, 사용자 원문(예: '고맙습니다')이 그대로 들어와도 canonical(예: '감사')
    데이터를 반환합니다. 응답에 데이터 품질 메타(검증 필드)도 함께 포함합니다.
    """
    data = supabase_service.get_motion_data(word)
    if not data:
        return {"status": "error", "message": f"'{word}'에 대한 데이터를 찾을 수 없습니다."}

    motion = data['motion_data'] if isinstance(data['motion_data'], dict) else {}
    keyframes = motion.get('keyframes', []) if isinstance(motion, dict) else []
    parent_chain = motion.get('parent_chain', {}) if isinstance(motion, dict) else {}

    # 첫 keyframe 기준 본 구성 검사 — 손가락 데이터 유무는 재생 정확도 판단의 핵심.
    has_fingers = False
    bone_count = 0
    if keyframes:
        bones = keyframes[0].get('bones', {}) if isinstance(keyframes[0], dict) else {}
        bone_count = len(bones)
        has_fingers = any(
            ('Hand' in n) and any(f in n for f in ('Thumb', 'Index', 'Middle', 'Ring', 'Pinky'))
            for n in bones.keys()
        )

    return {
        "status": "success",
        "word": data['word'],
        "resolved_from": data.get('resolved_from', word),
        "motion_data": data['motion_data'],
        "meta": {
            "keyframe_count": len(keyframes),
            "bone_count_kf0": bone_count,
            "has_fingers": has_fingers,
            "parent_chain_size": len(parent_chain),
            "space": motion.get('space') if isinstance(motion, dict) else None,
        },
    }

@router.get("/supabase/words")
async def get_supabase_words():
    """Supabase에 저장된 모든 단어 목록을 가져옵니다."""
    words = supabase_service.get_all_words()
    return {"status": "success", "words": words}

@router.get("/supabase/video-urls")
async def get_all_video_urls():
    """투명 배경 수어 영상 URL을 단어별로 일괄 반환합니다."""
    videos = supabase_service.get_all_video_urls()
    return {"status": "success", "videos": videos}

@router.get("/b2/token")
async def get_b2_token():
    """B2 Private 버킷 영상 재생을 위한 인증 토큰을 반환합니다.
    프론트엔드는 이 토큰을 영상 URL 뒤에 ?Authorization=TOKEN 으로 붙여 재생합니다.
    토큰은 24시간 유효하며, 캐싱되어 반복 호출 시 동일 토큰을 반환합니다."""
    try:
        from api.services.b2_storage import b2_storage
        info = b2_storage.get_base_info()
        return {"status": "success", **info}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/tokenize")
async def tokenize_sentence(request: TokenizeRequest):
    """문장을 모션 사전 기반으로 단어 배열로 분절합니다.

    - 사전 = 로컬 KSL 모션 인덱스 ∪ Supabase aliases (longest-match greedy)
    - 응답 tokens 는 재생 가능한 word 들을 순서대로 담음. source 가 'unknown' 인 항목은
      어느 사전에도 없는 substring 으로, 프론트에서 무시하거나 로깅 용도로 사용 가능.
    """
    tokens = motion_tokenizer.tokenize(request.text)
    playable = [t for t in tokens if t['source'] != 'unknown']
    return {
        "status": "success",
        "original": request.text,
        "tokens": tokens,
        "playable_count": len(playable),
        "playable_words": [t['word'] for t in playable],
    }

@router.get("/tokenize/stats")
async def tokenize_stats():
    """토크나이저 사전 통계 (디버그용)."""
    return {"status": "success", **motion_tokenizer.stats()}

@router.post("/upload-and-process")
async def upload_and_process_sign_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    word: str = Form(...)
):
    """사용자가 직접 촬영한 수어 영상(MP4)을 업로드받아,
    백그라운드에서 실시간으로 3D 관절을 추출 및 리타겟팅 보정하고
    Supabase DB에 즉시 Canonical(최우선 재생)로 자동 적재합니다.
    """
    # 1. 업로드 영상 임시 디렉토리 생성 및 보관
    temp_dir = os.path.join(os.getcwd(), "data", "temp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_video_path = os.path.join(temp_dir, f"uploaded_{word}.mp4")
    
    try:
        with open(temp_video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"임시 영상 파일 저장 실패: {str(e)}")

    # 2. 비동기 백그라운드 가공 및 적재 파이프라인 실행 정의
    def run_motion_pipeline():
        script_path = r"c:\Users\ComHolic\Desktop\ITDA_DB\src\_process_uploaded.py"
        log_path = os.path.join(temp_dir, "pipeline_last_run.log")
        
        print(f"[FastAPI Background] '{word}' 모션 추출 및 적재 파이프라인 시작...")
        try:
            with open(log_path, "w", encoding="utf-8") as log_file:
                # subprocess 가동하여 _process_uploaded.py 비동기 백그라운드 구동
                result = subprocess.run(
                    ["python", script_path, "--video_path", temp_video_path, "--word", word],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=True
                )
            print(f"[FastAPI Background] '{word}' 모션 추출/적재 성공 완료!")
        except subprocess.CalledProcessError as err:
            print(f"[FastAPI Background] ERROR: '{word}' 모션 추출 파이프라인 처리 중 치명적인 실패 발생!")
            print(f"  자세한 에러 정보는 다음 로그 파일에서 확인 가능: {log_path}")
        except Exception as e:
            print(f"[FastAPI Background] ERROR: 예기치 못한 스레드 예외: {str(e)}")

    # 3. 백그라운드 태스크 등록
    background_tasks.add_task(run_motion_pipeline)
    
    return {
        "status": "success",
        "word": word,
        "message": f"'{word}' 수어 영상 업로드 및 백그라운드 가공 스케줄링 완료! "
                   f"관절 추출 및 고품질 리타겟팅 보정이 완료되면 아바타가 즉시 이 버전을 재생합니다. "
                   f"진행 상세 경과는 'data/temp/pipeline_last_run.log' 파일에서 모니터링 가능합니다."
    }
