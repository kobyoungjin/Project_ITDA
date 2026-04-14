/**
 * retargeting.js - MediaPipe 좌표를 3D Bone 회전값으로 변환
 * 
 * ■ 핵심 로직
 *   1. MediaPipe 2D/3D 랜드마크 수신
 *   2. 특정 관절(손가락, 팔)의 각도 계산 (Vector math)
 *   3. 3D 캐릭터(Xbot)의 Bone Rotation에 매핑
 *   4. Lerp 보간은 avatar.js에서 수행
 */

class RetargetingEngine {
    constructor() {
        console.info("[ITDA Retargeting] 엔진 초기화됨");
    }

    /**
     * MediaPipe 결과를 아바타에 반영
     * @param {Object} results - MediaPipe Hands 결과
     */
    apply(results) {
        if (!results.multiHandLandmarks) return;

        results.multiHandLandmarks.forEach((landmarks, index) => {
            const handedness = results.multiHandedness[index].label; // "Left" or "Right"
            const prefix = handedness; // "Left" or "Right"

            // 예시: 검지 손가락 회전 매핑 (단순화된 예시)
            // 실제 수어 엔진에서는 각 마디별 벡터 내적을 통해 정확한 각도를 계산합니다.
            this.mapFinger(prefix, 'Index', landmarks, 5, 8);
            this.mapFinger(prefix, 'Middle', landmarks, 9, 12);
            this.mapFinger(prefix, 'Ring', landmarks, 13, 16);
            this.mapFinger(prefix, 'Pinky', landmarks, 17, 20);
            this.mapThumb(prefix, landmarks);
        });
    }

    mapFinger(side, name, landmarks, mcpIdx, tipIdx) {
        const mcp = landmarks[mcpIdx];
        const tip = landmarks[tipIdx];

        // 단순 Y축 차이를 이용한 굽힘 시뮬레이션
        const curl = (mcp.y - tip.y) * 2; 
        
        // Avatar의 Bone 이름 규칙에 맞춰 업데이트 (Xbot 기준)
        // 예: LeftHandIndex1, LeftHandIndex2, LeftHandIndex3
        const bone1 = `${side}Hand${name}1`;
        const bone2 = `${side}Hand${name}2`;
        const bone3 = `${side}Hand${name}3`;

        if (window.ITDAAvatar) {
            window.ITDAAvatar.updateBone(bone1, { x: 0, y: 0, z: curl });
            window.ITDAAvatar.updateBone(bone2, { x: 0, y: 0, z: curl * 1.2 });
            window.ITDAAvatar.updateBone(bone3, { x: 0, y: 0, z: curl * 1.5 });
        }
    }

    mapThumb(side, landmarks) {
        // 엄지는 별도의 각도 계산 필요
        const tip = landmarks[4];
        const mcp = landmarks[2];
        const curl = (mcp.x - tip.x) * (side === 'Left' ? 1 : -1);

        if (window.ITDAAvatar) {
            window.ITDAAvatar.updateBone(`${side}HandThumb1`, { x: 0, y: curl, z: 0 });
            window.ITDAAvatar.updateBone(`${side}HandThumb2`, { x: 0, y: curl, z: 0 });
        }
    }
}

window.ITDARetargeting = new RetargetingEngine();
