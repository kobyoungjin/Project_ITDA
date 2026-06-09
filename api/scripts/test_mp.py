import os
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
try:
    import mediapipe as mp
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(static_image_mode=True)
    print("SUCCESS: MediaPipe initialized")
except Exception as e:
    print(f"FAILURE: {e}")
