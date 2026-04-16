import os

# This script is just for reference of common Mixamo/RPM bone names
def print_common_bones():
    arm_bones = [
        "Hips", "Spine", "Spine1", "Spine2", "Neck", "Head",
        "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
        "RightShoulder", "RightArm", "RightForeArm", "RightHand",
        "RightHandThumb1", "RightHandThumb2", "RightHandThumb3",
        "RightHandIndex1", "RightHandIndex2", "RightHandIndex3",
        "RightHandMiddle1", "RightHandMiddle2", "RightHandMiddle3",
        "RightHandRing1", "RightHandRing2", "RightHandRing3",
        "RightHandPinky1", "RightHandPinky2", "RightHandPinky3"
    ]
    print("Expected Bone Names (with possible mixamorig_ prefix):")
    for b in arm_bones:
        print(f"- {b} / mixamorig{b}")

print_common_bones()
