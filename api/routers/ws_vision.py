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
        ws = self.active.get(session_id)
        if ws:
            await ws.send_text(ack.model_dump_json())

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
        
        # [NEW] 모션이 감지되면 액션 타임 초기화
        if motion_phase != "idle":
            manager.last_action_time[session_id] = time.time()
        
        # [개선안 2] Moving 전환 시 투표창 초기화 (잔상 제거)
        prev_phase = manager.last_motion_phase.get(session_id, "stable")
        if prev_phase in ("stable", "idle") and motion_phase == "moving":
            if session_id in manager.prediction_windows:
                manager.prediction_windows[session_id].clear()
                print(f"[Vision] 🧹 Motion detected. Clearing vote window.")
        manager.last_motion_phase[session_id] = motion_phase

        run_full_pipeline = motion_phase == "stable"

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
                
                # 2. 보정된 값으로 예측
                knn_result, knn_confidence = knn_classifier.predict(s_right, s_left)
                
                # 3. 다수결 투표 적용
                voted_result = manager._get_voted_result(session_id, knn_result)
                
                # 최종 결과 업데이트
                knn_result = voted_result
                if knn_result:
                    print(f"[KNN] OK {knn_result} ({knn_confidence:.1%})")
                    # [NEW] 문장 버퍼에 단어 추가 (중속 방지)
                    buf = manager.sentence_buffer[session_id]
                    if not buf or buf[-1] != knn_result:
                        buf.append(knn_result)
                        manager.last_action_time[session_id] = time.time()
                        print(f"[SentenceBuilder] 단어 추가: {knn_result} (현재 버퍼: {buf})")
                else:
                    # 임계값 미달 상세 로그 - 어느 단어를 예측했고 신뢰도가 얼마인지 출력
                    print(f"[KNN] MISS conf={knn_confidence:.3f} (threshold=0.50) - 최고 후보 신뢰도 부족")

        from api.services.slm_agent import slm_agent
        if knn_result:
            fast_pred = knn_result
        else:
            fast_pred = await slm_agent.predict_fast(raw, skip_ollama=not run_full_pipeline)

        # Draft 중간 송출은 공통
        await manager.send_ack(
            session_id,
            VisionAck(
                frame_id=frame.frame_id,
                status="processing",
                rag_result={"type": "draft", "text": fast_pred, "motion_phase": motion_phase,
                            "knn_confidence": round(knn_confidence, 3)},
                message=f"1차 예측 완료 ({motion_phase})",
                hand_analyses=hand_analyses or None,
                pose_analysis=pose_analysis_obj,
            ),
        )

        if not run_full_pipeline:
            # 손이 움직이는 동안에는 Draft만 보내고 종료
            return

        # Track 2: 1단계 RAG 데이터베이스 스캔 (모션 완료 시에만)
        search_keyword = fast_pred if fast_pred else "정지 상태"
        rag_data = rag_engine.retrieve_with_emotion(search_keyword)

        # Track 3: 1차 예측 + RAG 문맥 합성을 통한 최종 온기 보정
        final_text = await slm_agent.predict_with_rag(fast_pred, rag_data)

        rag_result = {
            "type": "final",
            "text": final_text,
            "emotions": rag_data.get('emotions', []) if rag_data else [],
            "video_url": rag_data.get('video_url', '') if rag_data else '',
            "motion_phase": motion_phase,
        }

        ms = (time.perf_counter() - recv_t) * 1000
        await manager.send_ack(
            session_id,
            VisionAck(
                frame_id=frame.frame_id,
                status="ok",
                rag_result=rag_result,
                message=f"최종 RAG 융합 ({ms:.1f}ms)",
                hand_analyses=hand_analyses or None,
                pose_analysis=pose_analysis_obj,
            ),
        )
        
        # [NEW] 문장 구성 트리거: idle 상태가 2초 유지되고 버퍼에 단어가 2개 이상일 때
        now = time.time()
        buf = manager.sentence_buffer[session_id]
        if motion_phase == "idle" and len(buf) > 1 and (now - manager.last_action_time[session_id]) > 2.0:
            print(f"[SentenceBuilder] 🚀 문장 구성 시작: {buf}")
            sentence = await slm_agent.build_sentence(buf)
            manager.sentence_buffer[session_id] = [] # 버퍼 초기화
            manager.last_action_time[session_id] = now
            
            sent_result = {
                "type": "final",
                "text": f"💬 {sentence}",
                "emotions": [],
                "video_url": "",
                "motion_phase": "idle",
            }
            await manager.send_ack(
                session_id,
                VisionAck(
                    frame_id=frame.frame_id,
                    status="ok",
                    rag_result=sent_result,
                    message="문장 완성",
                    hand_analyses=hand_analyses or None,
                    pose_analysis=pose_analysis_obj,
                )
            )

    except Exception as e:
        print(f"[Vision] Critical error in handle: {e}")
    finally:
        manager.processing[session_id] = False
        
        # [개선안 1] 보류된 최신 프레임이 있으면 즉시 연달아 처리 (비동기 루프)
        import asyncio
        next_raw = manager.pending_frames.get(session_id)
        if next_raw and session_id in manager.active:
            asyncio.create_task(_handle(session_id, next_raw))
