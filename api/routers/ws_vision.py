from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import logging
import time
from collections import deque, Counter

from api.core.websockets_schema import VisionFrame, VisionAck, HandAnalysis, PoseAnalysis
from api.services.rag_engine import rag_engine
from api.services.handshape_analyzer import analyze_hand, describe_for_slm
from api.services.pose_analyzer import analyze_pose

logger = logging.getLogger("itda.vision.router")
router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}
        self.processing: dict[str, bool] = {} # 세션별 처리 중 상태
        
        # 세션별 시계열 상태 저장소
        self.smoothed_states: dict[str, dict] = {} # {session_id: {'R': lms, 'L': lms}}
        self.prediction_windows: dict[str, deque] = {} # {session_id: deque}
        self.pending_frames: dict[str, dict | None] = {} # [개선안 1] 최신 대기 프레임
        self.last_motion_phase: dict[str, str] = {} # [개선안 2] 상태 전환 감지용
        self.ema_alpha = 0.6 # 민감도 향상 (높을수록 즉각 반응)
        
        # [NEW] 문장 구성기(Sentence Builder)용 상태
        self.sentence_buffer: dict[str, list[str]] = {}
        self.last_action_time: dict[str, float] = {}

    def _smooth_landmarks(self, session_id, side, new_lms):
        if not new_lms: return None
        
        if session_id not in self.smoothed_states:
            self.smoothed_states[session_id] = {'R': None, 'L': None}
        
        prev_lms = self.smoothed_states[session_id].get(side)
        if not prev_lms:
            self.smoothed_states[session_id][side] = new_lms
            return new_lms
        
        smoothed = []
        for n, p in zip(new_lms, prev_lms):
            smoothed.append({
                "x": p["x"] * (1 - self.ema_alpha) + n["x"] * self.ema_alpha,
                "y": p["y"] * (1 - self.ema_alpha) + n["y"] * self.ema_alpha,
                "z": p.get("z", 0) * (1 - self.ema_alpha) + n.get("z", 0) * self.ema_alpha
            })
        self.smoothed_states[session_id][side] = smoothed
        return smoothed

    def _get_voted_result(self, session_id, current_pred):
        if session_id not in self.prediction_windows:
            self.prediction_windows[session_id] = deque(maxlen=5) # 5프레임으로 단축
            
        if current_pred:
            self.prediction_windows[session_id].append(current_pred)
        
        window = self.prediction_windows[session_id]
        if not window: return None
            
        counts = Counter(window)
        most_common = counts.most_common(1)
        if most_common and most_common[0][1] >= 2: # 2회만 일치해도 인정 (빠른 반응)
            return most_common[0][0]
        return None

    async def connect(self, session_id: str, ws: WebSocket):
        self.active[session_id] = ws
        self.processing[session_id] = False

    def disconnect(self, session_id: str):
        self.active.pop(session_id, None)
        self.processing.pop(session_id, None)
        self.smoothed_states.pop(session_id, None)
        self.prediction_windows.pop(session_id, None)
        self.pending_frames.pop(session_id, None)
        self.last_motion_phase.pop(session_id, None)
        self.sentence_buffer.pop(session_id, None)
        self.last_action_time.pop(session_id, None)

    async def send_ack(self, session_id: str, ack: VisionAck):
        """[수정] 모든 활성 클라이언트에게 브로드캐스트 (다른 창 연동용)"""
        json_data = ack.model_dump_json()
        disconnected = []
        for sid, ws in self.active.items():
            try:
                await ws.send_text(json_data)
            except Exception:
                disconnected.append(sid)
        
        for sid in disconnected:
            self.disconnect(sid)

manager = ConnectionManager()

@router.websocket("/ws/vision")
async def vision_socket(ws: WebSocket):
    await ws.accept()
    session_id: str = f"anon_{int(time.time())}"
    try:
        raw_first = await ws.receive_text()
        data = json.loads(raw_first)
        session_id = data.get("session_id", session_id)
        await manager.connect(session_id, ws)
        await _handle(session_id, data)

        while True:
            raw = await ws.receive_text()
            await _handle(session_id, json.loads(raw))

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(session_id)

async def _handle(session_id: str, raw: dict):
    # [개선안 1] 처리 중이면 최신 프레임을 보관만 하고 리턴 (Drop 방지)
    if manager.processing.get(session_id, False):
        manager.pending_frames[session_id] = raw
        return

    manager.processing[session_id] = True
    manager.pending_frames[session_id] = None # 처리 시작하므로 보관함 비움

    if session_id not in manager.sentence_buffer:
        manager.sentence_buffer[session_id] = []
        manager.last_action_time[session_id] = time.time()

    # ─── [2초 정적 대기 상태 판단 및 문장 자동 완성 가드] ───
    now = time.time()
    buf = manager.sentence_buffer[session_id]
    meta = dict(raw.get("meta_features") or {})
    motion_phase = meta.get("motion_phase", "stable")
    
    # 모션이 감지되면(움직임 속도가 있거나 moving 상태일 때) 액션 타임 초기화
    if motion_phase != "idle":
        manager.last_action_time[session_id] = now

    # 2초간 유효한 움직임이 전혀 감지되지 않고 가만히 정지/Idle 상태에 있을 때
    if (now - manager.last_action_time[session_id]) >= 2.0:
        # ① 버퍼에 단어가 쌓여 있는 경우 -> 2초간 멈춘 시점에 문장을 최종 합성하여 발송합니다!
        if len(buf) >= 1:
            print(f"[SentenceBuilder] 🚀 2초간 정적 상태 유지. 단어 누적 문장 구성 시작: {buf}")
            from api.services.slm_agent import slm_agent
            sentence = await slm_agent.build_sentence(buf)
            manager.sentence_buffer[session_id] = [] # 버퍼 리셋
            manager.last_action_time[session_id] = now
            
            sent_result = {
                "type": "final",
                "text": f"💬 {sentence}",
                "emotions": ["차분함"],
                "video_url": "",
                "motion_phase": "idle",
                "knn_confidence": 1.0
            }
            await manager.send_ack(
                session_id,
                VisionAck(
                    frame_id=raw.get("frame_id", -1),
                    status="ok",
                    rag_result=sent_result,
                    message="2초간 정적 대기로 인한 문장 완성",
                )
            )
            manager.processing[session_id] = False
            return
            
        # ② 버퍼가 완전히 비어있는데도 2초간 계속 가만히 서 있을 때 -> 단순 대기 자세 ("대기 중")로 리셋 송출
        else:
            await manager.send_ack(
                session_id,
                VisionAck(
                    frame_id=raw.get("frame_id", -1),
                    status="ok",
                    rag_result={
                        "type": "final",
                        "text": "대기 중",
                        "emotions": [],
                        "video_url": "",
                        "motion_phase": "idle",
                        "knn_confidence": 0.0
                    },
                    message="2초간 무동작 정지로 인한 단순 대기 자세 리셋",
                )
            )
            # 대기 중일 때는 액션 타임을 계속 밀어서 무한 루프 송출 방지
            manager.last_action_time[session_id] = now
            manager.processing[session_id] = False
            return

    recv_t = time.perf_counter()
    try:
        try:
            frame = VisionFrame(**raw)
        except Exception as e:
            ack = VisionAck(frame_id=raw.get("frame_id", -1), status="error", message=str(e))
            await manager.send_ack(session_id, ack)
            return

        # ──────── [P0] Handshape 분류 (21 keypoint 기반) ────────
        hand_analyses: list[HandAnalysis] = []
        for h in raw.get("hands", []):
            result = analyze_hand(h)
            if result:
                hand_analyses.append(HandAnalysis(**result))

        handshape_summary = describe_for_slm([a.model_dump() for a in hand_analyses])

        # ──────── [P0] Pose 분석 (어깨/팔꿈치/손목) ────────
        pose_analysis_obj: PoseAnalysis | None = None
        pose_summary = "상체 감지 안됨"
        pose_raw = raw.get("pose")
        if pose_raw:
            pose_res = analyze_pose(pose_raw)
            if pose_res:
                pose_analysis_obj = PoseAnalysis(**pose_res)
                pose_summary = pose_res["summary"]

        meta = dict(raw.get("meta_features") or {})
        meta["handshapes"] = [a.handshape for a in hand_analyses]
        meta["handshape_summary"] = handshape_summary
        meta["pose_summary"] = pose_summary
        if pose_analysis_obj:
            meta["wrist_regions"] = [pose_analysis_obj.wrist_region_R, pose_analysis_obj.wrist_region_L]
            meta["elbow_bends"] = [pose_analysis_obj.elbow_bend_R, pose_analysis_obj.elbow_bend_L]
        raw["meta_features"] = meta

        motion_phase = meta.get("motion_phase", "stable")
        
        # 모션이 감지되면 액션 타임 초기화
        if motion_phase != "idle":
            manager.last_action_time[session_id] = now
        
        # [개선안 2] Moving 전환 시 투표창 초기화 (잔상 제거)
        prev_phase = manager.last_motion_phase.get(session_id, "stable")
        if prev_phase in ("stable", "idle") and motion_phase == "moving":
            if session_id in manager.prediction_windows:
                manager.prediction_windows[session_id].clear()
                print(f"[Vision] 🧹 Motion detected. Clearing vote window.")
        manager.last_motion_phase[session_id] = motion_phase

        # [개선] stable(정지) 단계뿐만 아니라 settling(감속) 단계에서도 인식을 시도하여 반응성 대폭 향상
        run_full_pipeline = motion_phase in ("stable", "settling")

        knn_result = None
        knn_confidence = 0.0
        if run_full_pipeline:
            from api.services import knn_classifier
            hands_raw = raw.get("hands") or []
            if hands_raw and knn_classifier.is_model_ready():
                right_lms = None
                left_lms = None

                for h in hands_raw:
                    label_side = h.get("handedness", "Right")
                    kps = h.get("keypoints") or []
                    lms = [{"x": kp["x"], "y": kp["y"], "z": kp.get("z", 0)} for kp in kps]
                    
                    if label_side == "Right":
                        right_lms = lms
                    else:
                        left_lms = lms
                
                # 1. 필터 적용 (Smoothing)
                s_right = manager._smooth_landmarks(session_id, 'R', right_lms)
                s_left = manager._smooth_landmarks(session_id, 'L', left_lms)
                
                # 2. 보정된 값으로 예측 (Pose 데이터 추가 전달)
                knn_result, knn_confidence = knn_classifier.predict(s_right, s_left, pose_raw)
                
                # 3. 다수결 투표 적용
                voted_result = manager._get_voted_result(session_id, knn_result)
                
                # 최종 결과 업데이트
                knn_result = voted_result
                if knn_result:
                    print(f"[KNN] OK {knn_result} ({knn_confidence:.1%})")
                    # [NEW] 문장 버퍼에 단어 추가 (중복 방지)
                    buf = manager.sentence_buffer[session_id]
                    if not buf or buf[-1] != knn_result:
                        buf.append(knn_result)
                        manager.last_action_time[session_id] = time.time()
                        print(f"[SentenceBuilder] 단어 추가: {knn_result} (현재 버퍼: {buf})")
                else:
                    # 임계값 미달 상세 로그 - 어느 단어를 예측했고 신뢰도가 얼마인지 출력
                    print(f"[KNN] MISS conf={knn_confidence:.3f} (threshold={knn_classifier.CONFIDENCE_THRESHOLD:.2f}) - 최고 후보 신뢰도 부족")

        # ──────── [실시간 최적화 혁신 파이프라인] ────────
        # ① KNN 예측이 완벽하게 성공한 경우: 즉시 초고속 패스트 패스(Fast-Path)로 최종 번역을 송출하고 종료합니다.
        #    이로써 Ollama/Gemini 호출과 RAG 데이터베이스 스캔으로 인한 수 초간의 답답한 지연을 100% 제거(0.001초 실시간성 구현)합니다.
        if knn_result:
            await manager.send_ack(
                session_id,
                VisionAck(
                    frame_id=frame.frame_id,
                    status="ok",
                    rag_result={
                        "type": "final",
                        "text": knn_result,
                        "emotions": ["차분함"],
                        "video_url": "",
                        "motion_phase": motion_phase,
                        "knn_confidence": round(knn_confidence, 3)
                    },
                    message="최종 확정 (KNN 초고속 패스트 패스)",
                    hand_analyses=hand_analyses or None,
                    pose_analysis=pose_analysis_obj,
                ),
            )
            return

        # ② KNN 예측이 실패하거나 신뢰도가 미달인 경우:
        #    불완전한 랜드마크 데이터로 LLM을 호출하여 엉뚱한 환각 단어들만 지어내던 오작동(특정 단어 도배 현상)을 완벽히 배제합니다.
        #    즉시 "미인식" 상태로 안전하게 확정 처리하여 조기 반환합니다.
        await manager.send_ack(
            session_id,
            VisionAck(
                frame_id=frame.frame_id,
                status="ok",
                rag_result={"type": "final", "text": "미인식", "motion_phase": motion_phase, "knn_confidence": 0.0},
                message="인식 실패 (KNN 신뢰도 미달)",
                hand_analyses=hand_analyses or None,
                pose_analysis=pose_analysis_obj,
            ),
        )
        return

    except Exception as e:
        print(f"[Vision] Critical error in handle: {e}")
    finally:
        manager.processing[session_id] = False
        
        # [개선안 1] 보류된 최신 프레임이 있으면 즉시 연달아 처리 (비동기 루프)
        import asyncio
        next_raw = manager.pending_frames.get(session_id)
        if next_raw and session_id in manager.active:
            asyncio.create_task(_handle(session_id, next_raw))
