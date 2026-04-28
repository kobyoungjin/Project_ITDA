"""Debug smoothing effect on first frame."""
import sys, io, os, json, importlib
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import api.tools.mediapipe_retarget as m
importlib.reload(m)

d = r'C:\Users\ComHolic\Desktop\data\[라벨]01_real_word_keypoint\01\NIA_SL_WORD0001_REAL01_F'
files = sorted(f for f in os.listdir(d) if f.endswith('_keypoints.json'))

print('=== Frame 0~4 raw RShoulder.y / RElbow.y ===')
for i in range(5):
    with open(os.path.join(d, files[i]), encoding='utf-8') as f: j = json.load(f)
    p = j['people']['pose_keypoints_3d']
    sh_y_raw = p[2*4+1]
    el_y_raw = p[3*4+1]
    sh_y_flip = -sh_y_raw
    el_y_flip = -el_y_raw
    diff = el_y_flip - sh_y_flip
    print(f'  frame {i}: shoulder.y_raw={sh_y_raw:+.4f}  elbow.y_raw={el_y_raw:+.4f}  -> flipped diff(el-sh)={diff:+.4f}  ({"elbow BELOW shoulder = arms-down" if diff<0 else "elbow ABOVE shoulder = arms-up"})')

# Smoothed frame 0
all_frames = []
for fn in files:
    with open(os.path.join(d, fn), encoding='utf-8') as f: j = json.load(f)
    pose = m._openpose_pose_to_dict(j['people']['pose_keypoints_3d'])
    all_frames.append({'time': 0, 'pose': pose, 'hand_right':[], 'hand_left':[]})

smoothed = m._smooth_positions_centered(all_frames, window=5)
sf0 = smoothed[0]['pose']
print(f'\n=== smoothed frame 0 (avg of frames 0,1,2 since lo=0,hi=3) ===')
print(f'  RShoulder y={sf0["right_shoulder"]["y"]:+.4f}')
print(f'  RElbow    y={sf0["right_elbow"]["y"]:+.4f}')
sh = np.array([sf0['right_shoulder']['x'], sf0['right_shoulder']['y'], sf0['right_shoulder']['z']])
el = np.array([sf0['right_elbow']['x'],    sf0['right_elbow']['y'],    sf0['right_elbow']['z']])
t = el - sh
tn = t / np.linalg.norm(t)
print(f'  target_n = {tn}')
print(f'  Y sign: {tn[1]:+.3f}  ({"DOWN OK" if tn[1]<0 else "UP - PROBLEM"})')

# Now feed this through retarget_arm_chain
out = m.retarget_arm_chain(sh, el,
                           np.array([sf0['right_wrist']['x'], sf0['right_wrist']['y'], sf0['right_wrist']['z']]),
                           'Right')
print(f'\n  retarget_arm_chain RightArm: {out["RightArm"]}')

# Verify by applying quat to rest
import math
q = out['RightArm']
qx,qy,qz,qw = q['x'], q['y'], q['z'], q['w']
qxyz = np.array([qx,qy,qz])
rest = np.array([-1.0, 0, 0])
v = rest
cross1 = np.cross(qxyz, v)
cross2 = np.cross(qxyz, cross1 + qw*v)
result = v + 2*cross2
print(f'  applying q to rest=(-1,0,0): {result}')
print(f'  expected: target_n = {tn}')
print(f'  match: {np.allclose(result, tn, atol=0.01)}')
