from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import logging
import time

from api.core.websockets_schema import VisionFrame, VisionAck, HandAnalysis, PoseAnalysis
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
        try:
            raw_first = await ws.receive_text()
            data = json.loads(raw_first)
            session_id = data.get("session_id", session_id)
        except (WebSocketDisconnect, RuntimeError):
            return

        await manager.connect(session_id, ws)
        await _handle(session_id, data)

        while True:
            try:
                raw = await ws.receive_text()
                await _handle(session_id, json.loads(raw))
            except (WebSocketDisconnect, RuntimeError):
                break

    except Exception as e:
        logger.error(f"[vision_socket] Unexpected error: {e}")
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

        # Track 1: Rule-based 1차 예측 (Ollama 비활성화 — 웹캠 인식팀 담당)
        from api.services.slm_agent import _rule_based_predict
        fast_pred = _rule_based_predict(meta)

        # [P2] 모션 phase 기반 게이팅:
        #   moving / settling → Draft 만 송출하고 RAG+Track3 생략 (서버 부하 및 UI 깜빡임 방지)
        #   stable / idle    → 풀 파이프라인 실행 (수어 한 단어 완성 시점)
        motion_phase = meta.get("motion_phase", "stable")
        run_full_pipeline = motion_phase in ("stable", "idle")

        # Draft 중간 송출은 공통
        await manager.send_ack(
            session_id,
            VisionAck(
                frame_id=frame.frame_id,
                status="processing",
                rag_result={"type": "draft", "text": fast_pred, "motion_phase": motion_phase},
                message=f"1차 예측 완료 ({motion_phase})",
                hand_analyses=hand_analyses or None,
                pose_analysis=pose_analysis_obj,
            ),
        )

        if not run_full_pipeline:
            # 손이 움직이는 동안에는 Draft만 보내고 종료
            return

        # Track 2: Rule-based 예측 결과를 직접 사용 (RAG 제거됨)
        final_text = fast_pred if fast_pred else "정지 상태"

        rag_result = {
            "type": "final",
            "text": final_text,
            "emotions": [],
            "video_url": "",
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
