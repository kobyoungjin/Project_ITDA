"""
_mp_worker.py — MediaPipe 랜드마크 추출 워커 (subprocess 격리용)

호출:  python _mp_worker.py <video_path> <model_path>
출력:  JSON → stdout  ({"frames": [...], "detected": N, "total": M})
       오류:           ({"error": "...", "traceback": "..."})

별도 프로세스로 실행해 MediaPipe 네이티브 크래시로부터 서버를 보호.
PyAV를 사용해 WebM/VP9 포함 모든 브라우저 녹화 포맷을 읽습니다.
"""

import json
import sys


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "인자 부족: video_path, model_path 필요"}))
        sys.exit(1)

    video_path = sys.argv[1]
    model_path = sys.argv[2]

    try:
        import numpy as np

        # ── PyAV로 프레임 읽기 (WebM/VP8/VP9/MP4 모두 지원) ──────────────
        try:
            import av
        except ImportError:
            print(json.dumps({"error": "PyAV 미설치: pip install av"}))
            sys.exit(1)

        try:
            container = av.open(video_path)
        except Exception as e:
            print(json.dumps({"error": f"영상 열기 실패: {e}"}))
            sys.exit(1)

        try:
            video_stream = container.streams.video[0]
            avg_rate = video_stream.average_rate
            fps = float(avg_rate) if avg_rate else 30.0
        except (IndexError, Exception):
            fps = 30.0

        all_frames: list = []
        idx = 0
        try:
            for packet in container.demux(video=0):
                for frame in packet.decode():
                    rgb = frame.to_ndarray(format="rgb24")
                    all_frames.append((idx, rgb))
                    idx += 1
        except Exception:
            pass
        finally:
            container.close()

        if not all_frames:
            print(json.dumps({"error": "영상 프레임 읽기 실패 — 빈 영상이거나 손상된 파일입니다."}))
            sys.exit(1)

        # ── MediaPipe 초기화 ───────────────────────────────────────────
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        from mediapipe import Image as MpImage, ImageFormat

        base_options = mp_python.BaseOptions(model_asset_path=model_path)
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.3,
            min_pose_presence_confidence=0.3,
        )

        IDX = {
            "left_shoulder": 11, "right_shoulder": 12,
            "left_elbow":    13, "right_elbow":    14,
            "left_wrist":    15, "right_wrist":    16,
        }

        frames_out = []
        with vision.PoseLandmarker.create_from_options(options) as landmarker:
            for frame_no, rgb in all_frames:
                rgb_c = np.ascontiguousarray(rgb, dtype=np.uint8)
                mp_image = MpImage(image_format=ImageFormat.SRGB, data=rgb_c)
                result = landmarker.detect(mp_image)

                if result.pose_landmarks:
                    lm = result.pose_landmarks[0]
                    frames_out.append({
                        "time": round(frame_no / fps, 4),
                        "pose": {
                            key: {"x": lm[i].x, "y": lm[i].y, "z": lm[i].z}
                            for key, i in IDX.items()
                        },
                    })

        print(json.dumps({
            "frames": frames_out,
            "total": len(all_frames),
            "detected": len(frames_out),
        }))

    except Exception as e:
        import traceback
        print(json.dumps({
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
