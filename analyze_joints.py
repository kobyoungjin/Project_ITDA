import json

path = r'c:\Users\ComHolic\Documents\GitHub\Project_ITDA\frontend\data\ksl_motions\공개.json'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

print('=== 1.3초 전후 관절 비교 분석 ===')
print()
for kf in data['keyframes']:
    t = kf['time']
    if 1.1 <= t <= 1.5:
        bones = kf['bones']
        rfa = bones.get('RightForeArm', {})
        lfa = bones.get('LeftForeArm', {})
        rh  = bones.get('RightHand', {})
        lh  = bones.get('LeftHand', {})
        
        print(f'--- time={t:.4f}s ---')
        print(f'  RFA: x={rfa.get("x",0): .5f} y={rfa.get("y",0): .5f} z={rfa.get("z",0): .5f} w={rfa.get("w",0): .5f}')
        print(f'  LFA: x={lfa.get("x",0): .5f} y={lfa.get("y",0): .5f} z={lfa.get("z",0): .5f} w={lfa.get("w",0): .5f}')
        print(f'  RH:  x={rh.get("x",0): .5f} y={rh.get("y",0): .5f} z={rh.get("z",0): .5f} w={rh.get("w",0): .5f}')
        print(f'  LH:  x={lh.get("x",0): .5f} y={lh.get("y",0): .5f} z={lh.get("z",0): .5f} w={lh.get("w",0): .5f}')
        
        # 미러링 관계 확인
        mirror_lfa_y = -lfa.get('y',0)
        mirror_lfa_z = -lfa.get('z',0)
        print(f'  Mirror(LFA->RFA): y={mirror_lfa_y: .5f} z={mirror_lfa_z: .5f} w={lfa.get("w",0): .5f}')
        print(f'  Actual RFA:       y={rfa.get("y",0): .5f} z={rfa.get("z",0): .5f} w={rfa.get("w",0): .5f}')
        print()
