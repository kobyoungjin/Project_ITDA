from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import logging
import time

from api.core.websockets_schema import VisionFrame, VisionAck, HandAnalysis, PoseAnalysis
from api.services.rag_engine import rag_engine
from api.services.handshape_analyzer import analyze_hand, describe_for_slm
from api.services.pose_analyzer import analyze_pose

logger = logging.getLogger("itda.vision.router")
router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}
        self.processing: dict[str, bool] = {} # [과제 3] 세션별 처리 상태(Lock) 추적

    async def connect(self, session_id: str, ws: WebSocket):
        self.active[session_id] = ws
        self.processing[session_id] = False

    def disconnect(self, session_id: str):
        self.active.pop(session_id, None)
        self.processing.pop(session_id, None)

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
    # [과제 3] Lock 기반 호출 제어 (충돌 및 서버 과부하 방지)
    if manager.processing.get(session_id, False):
        return
    manager.processing[session_id] = True

    recv_t = time.perf_counter()
    try:
        try:
            frame = VisionFrame(**raw)
        except Exception as e:
            ack = VisionAck(frame_id=raw.get("frame_id", -1), status="error", message=str(e))
            await manager.send_ack(session_id, ack)
            return

        # ──────── [P0] Handshape 분류 (21 keypoint 기반) ────────
        # 각 손을 독립적으로 분석해 KSL 수형(FIST/PALM/POINT/V/L/OK)으로 분류,
        # SLM 프롬프트에 주입 가능한 자연어 요약도 함께 준비.
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

        # meta_features 에 통합 주입 — SLM 프롬프트가 이 값들을 소비
        meta = dict(raw.get("meta_features") or {})
        meta["handshapes"] = [a.handshape for a in hand_analyses]
        meta["handshape_summary"] = handshape_summary
        meta["pose_summary"] = pose_summary
        if pose_analysis_obj:
            meta["wrist_regions"] = [pose_analysis_obj.wrist_region_R, pose_analysis_obj.wrist_region_L]
            meta["elbow_bends"] = [pose_analysis_obj.elbow_bend_R, pose_analysis_obj.elbow_bend_L]
        raw["meta_features"] = meta

        # ──────── [3단계: 하이브리드 번역 파이프라인] ────────

        # [P2] 모션 phase 기반 게이팅:
        #   moving / settling → 무거운 AI 호출 생략하고 빠른 Draft만 송출
        #   stable / idle    → 풀 파이프라인 실행
        motion_phase = meta.get("motion_phase", "stable")
        run_full_pipeline = motion_phase in ("stable", "idle")

        # ── [KNN 초고속 판정] ──────────────────────────────────
        # 훈련된 KNN 모델이 있으면 Gemini 호출 전에 먼저 시도
        # → 신뢰도 60% 이상이면 AI 없이 0.001초만에 번역 확정
        knn_result = None
        knn_confidence = 0.0
        if run_full_pipeline:
            from api.services import knn_classifier
            hands_raw = raw.get("hands") or []
            if hands_raw and knn_classifier.is_model_ready():
                first_hand = hands_raw[0]
                kps = first_hand.get("keypoints") or []
                # keypoints를 landmarks 형식으로 변환
                lms = [{"x": kp["x"], "y": kp["y"], "z": kp.get("z", 0)} for kp in kps]
                knn_result, knn_confidence = knn_classifier.predict(lms)
                if knn_result:
                    print(f"[KNN] ✅ {knn_result} (신뢰도 {knn_confidence:.1%}) — Gemini 생략")

        from api.services.slm_agent import slm_agent
        # KNN이 확실하게 맞추면 Gemini 건너뜀, 아니면 AI 분석
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
            "emotions": rag_data.get('emotions', []),
            "video_url": rag_data.get('video_url', ''),
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
    finally:
        # 정상/에러 관계없이 작업이 끝나면 Lock 해제
        manager.processing[session_id] = False
