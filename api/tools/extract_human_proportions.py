import cv2
import mediapipe as mp
import numpy as np
import json
import math

def calculate_distance(p1, p2):
    # 3D 공간상의 유클리드 거리 계산
    return math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2 + (p1.z - p2.z)**2)

def extract_proportions(video_path, output_json):
    mp_holistic = mp.solutions.holistic
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        print(f"[오류] 비디오를 열 수 없습니다: {video_path}")
        return

    print("[알림] 사람의 골격, 손가락 및 이목구비 정밀 측정을 시작합니다...")
    
    proportions = {}
    
    # MediaPipe Holistic: 신체, 얼굴(468개 랜드마크), 양손을 모두 가장 정밀하게 추적하는 최고 수준 모델
    with mp_holistic.Holistic(
        static_image_mode=False,
        model_complexity=2, # 최고 정밀도
        enable_segmentation=False,
        refine_face_landmarks=True) as holistic: # 이목구비 정밀 추적 활성화
        
        while cap.isOpened():
            success, image = cap.read()
            if not success:
                break
                
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            results = holistic.process(image_rgb)
            
            # 1. 신체 뼈대 (어깨, 팔) 정밀 측정
            if results.pose_landmarks:
                landmarks = results.pose_landmarks.landmark
                
                left_shoulder = landmarks[mp_holistic.PoseLandmark.LEFT_SHOULDER]
                right_shoulder = landmarks[mp_holistic.PoseLandmark.RIGHT_SHOULDER]
                shoulder_width = calculate_distance(left_shoulder, right_shoulder)
                
                left_elbow = landmarks[mp_holistic.PoseLandmark.LEFT_ELBOW]
                left_wrist = landmarks[mp_holistic.PoseLandmark.LEFT_WRIST]
                left_upper_arm = calculate_distance(left_shoulder, left_elbow)
                left_forearm = calculate_distance(left_elbow, left_wrist)
                
                right_elbow = landmarks[mp_holistic.PoseLandmark.RIGHT_ELBOW]
                right_wrist = landmarks[mp_holistic.PoseLandmark.RIGHT_WRIST]
                right_upper_arm = calculate_distance(right_shoulder, right_elbow)
                right_forearm = calculate_distance(right_elbow, right_wrist)
                
                proportions['pose'] = {
                    'shoulder_width': shoulder_width,
                    'left_upper_arm': left_upper_arm,
                    'left_forearm': left_forearm,
                    'right_upper_arm': right_upper_arm,
                    'right_forearm': right_forearm
                }
                
            # 2. 이목구비 (눈 사이, 입 크기 등 468개 랜드마크 중 핵심 비율 추출)
            if results.face_landmarks:
                face = results.face_landmarks.landmark
                left_eye = face[33]
                right_eye = face[263]
                eye_distance = calculate_distance(left_eye, right_eye)
                
                mouth_left = face[61]
                mouth_right = face[291]
                mouth_width = calculate_distance(mouth_left, mouth_right)
                
                nose_tip = face[1]
                chin = face[152]
                face_length = calculate_distance(nose_tip, chin)
                
                proportions['face'] = {
                    'eye_distance': eye_distance,
                    'mouth_width': mouth_width,
                    'lower_face_length': face_length
                }
                
            # 3. 손가락 뼈대 정밀 측정 (손바닥, 주요 손가락 길이)
            if results.left_hand_landmarks:
                hand = results.left_hand_landmarks.landmark
                palm_length = calculate_distance(hand[0], hand[9]) # 손목부터 중지 첫마디
                index_length = calculate_distance(hand[5], hand[8]) # 검지 전체 길이
                proportions['left_hand'] = {
                    'palm_length': palm_length,
                    'index_finger_length': index_length
                }
                
            if results.right_hand_landmarks:
                hand = results.right_hand_landmarks.landmark
                palm_length = calculate_distance(hand[0], hand[9])
                index_length = calculate_distance(hand[5], hand[8])
                proportions['right_hand'] = {
                    'palm_length': palm_length,
                    'index_finger_length': index_length
                }
                
            # 신체, 얼굴, 손 데이터가 모두 수학적으로 정밀하게 추출되면 즉시 측정 종료
            if 'pose' in proportions and 'face' in proportions and 'right_hand' in proportions:
                break
                
    cap.release()
    
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(proportions, f, indent=4, ensure_ascii=False)
        
    print(f"\n[성공] 수학적으로 계산된 정밀 골격/이목구비 데이터가 저장되었습니다: {output_json}")
    print("[분석결과] 추출된 데이터는 아바타를 원본 사람과 1:1로 리스케일링하는데 사용됩니다.")

if __name__ == "__main__":
    extract_proportions("sample.mp4", "human_proportions.json")
