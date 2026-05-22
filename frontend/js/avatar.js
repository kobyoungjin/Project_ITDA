/**
 * avatar.js  ─  Step 5: Three.js RobotExpressive 아바타 씬
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ── 해부학적 제약 조건 (BONE_CONSTRAINTS) ─────────────────────
const BONE_CONSTRAINTS = {
  Shoulder: { y: [-0.2, 0.2], z: [-0.15, 0.15] },
  Arm: { z: [-Math.PI, Math.PI / 2] },
  UpperArm: { z: [-Math.PI, Math.PI / 2] },
  ForeArm: { x: [0, Math.PI * 0.8] },
  Hand: { x: [-0.5, 0.5], y: [-0.5, 0.5] },
  Thumb1: { x: [-0.3, 0.3], y: [-0.3, 0.6] },
  Thumb2: { x: [0, 0.5] },
  Thumb3: { x: [0, 0.5] },
  Index1: { x: [0, 1.5] },
  Index2: { x: [0, 1.5] },
  Index3: { x: [0, 1.5] },
  Middle1: { x: [0, 1.5] },
  Middle2: { x: [0, 1.5] },
  Middle3: { x: [0, 1.5] },
  Ring1: { x: [0, 1.5] },
  Ring2: { x: [0, 1.5] },
  Ring3: { x: [0, 1.5] },
  Pinky1: { x: [0, 1.5] },
  Pinky2: { x: [0, 1.5] },
  Pinky3: { x: [0, 1.5] },
};

console.log('[ITDA Avatar] ✅ avatar.js 로드됨. THREE 버전:', THREE.REVISION);

// ── 씬 ───────────────────────────────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x02040a);
scene.fog = new THREE.FogExp2(0x02040a, 0.05);

// ── 렌더러 및 카메라 (모바일 컨테이너 대응) ──────────────────────
const canvas = document.querySelector('#three-canvas');
const container = document.querySelector('#avatar-area');

const getAppSize = () => {
  const target = document.querySelector('#avatar-area') || document.querySelector('#app-container');
  let width = target ? target.clientWidth : window.innerWidth;
  let height = target ? target.clientHeight : window.innerHeight;
  if (width === 0) width = Math.min(window.innerWidth, 450);
  if (height === 0) height = window.innerHeight * 0.6;
  return { width, height };
};

const initialSize = getAppSize();

const camera = new THREE.PerspectiveCamera(40, initialSize.width / initialSize.height, 0.1, 100);
// 카메라를 뒤로 당겨 전체 아바타가 보이도록 기본 거리를 늘림
camera.position.set(0, 1.35, 3.2);

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(initialSize.width, initialSize.height);
renderer.shadowMap.enabled = true;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;

// ── 컨트롤 (각도 및 크기 고정) ───────────────────────────────
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = false;
controls.target.set(0, 1.35, 0); // 상체 중심
controls.enableRotate = false;  // 회전 방지
controls.enableZoom = false;    // 확대/축소 방지
controls.enablePan = false;     // 이동 방지
controls.update();

// ── 조명 (표준) ───────────────────────────────────────────────
scene.add(new THREE.AmbientLight(0xffffff, 1.5));
const dirLight = new THREE.DirectionalLight(0xffffff, 2.0);
dirLight.position.set(2, 5, 5);
dirLight.castShadow = true;
scene.add(dirLight);

// ── 바닥 그리드 ───────────────────────────────────────────────
const grid = new THREE.GridHelper(20, 30, 0x1a1a2e, 0x1a1a2e);
grid.position.y = -0.01;
scene.add(grid);

// ── 내부 상태 ─────────────────────────────────────────────────
let model = null;
let mixer = null;
let headMesh = null;
let bones = {};
let initialBoneQuats = {};
let morphIndex = {};
const _boneMarkers = {};

const clock = new THREE.Clock();

// ── 임시 벡터 (getTipPos 연산용) ────────────────────────────
const _tmpV1 = new THREE.Vector3();
const _tmpV2 = new THREE.Vector3();

const jstEl = document.getElementById('joint-status');

// ── 스켈레톤 뷰 — animate IIFE 이전에 선언해야 TDZ 오류 없음 ──
const skeletonGroup = new THREE.Group();
scene.add(skeletonGroup);
skeletonGroup.visible = false;

const _skJoints = [];
const _skBones = [];
const _jMat = new THREE.MeshStandardMaterial({ color: 0x00ff88, emissive: 0x004422 });
const _bMat = new THREE.MeshStandardMaterial({ color: 0x00aaff, transparent: true, opacity: 0.6 });
const _jGeo = new THREE.SphereGeometry(0.015, 12, 12);

for (let i = 0; i < 75; i++) {
  const m = new THREE.Mesh(_jGeo, _jMat);
  m.visible = false;
  skeletonGroup.add(m);
  _skJoints.push(m);
}

const _HC = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17]];
const _PC = [[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24], [23, 25], [25, 27], [24, 26], [26, 28]];
const _allC = [];
_HC.forEach(c => _allC.push([c[0], c[1]]));
_HC.forEach(c => _allC.push([c[0] + 21, c[1] + 21]));
_PC.forEach(c => _allC.push([c[0] + 42, c[1] + 42]));
_allC.push([57, 0]); _allC.push([58, 21]);

_allC.forEach(() => {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(0.005, 0.005, 1, 6), _bMat);
  skeletonGroup.add(m);
  _skBones.push(m);
});

window.ITDA_skeletonUpdatedThisFrame = false;

// ── 아바타 초기화 (스켈레톤 전용 모드) ────────────────────────
// 3D GLB 모델은 사용하지 않으므로 곧바로 스켈레톤 뷰로 시작한다.
function initAvatar() {
  console.info('[ITDA Avatar] 스켈레톤 전용 모드로 시작');
  if (jstEl) jstEl.textContent = '3D 모델 비활성화';
  const statusEl = document.getElementById('model-status');
  if (statusEl) {
    statusEl.textContent = '⚠️ 3D 모델 비활성화';
    statusEl.classList.remove('loaded');
  }
  _setViewMode('skeleton');
  window.dispatchEvent(new CustomEvent('itda:avatar:ready'));
}

initAvatar();

// ── 반응형 리사이즈 ───────────────────────────────────────────
window.addEventListener('resize', () => {
  const { width, height } = getAppSize();
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
});
setTimeout(() => window.dispatchEvent(new Event('resize')), 100);

// ── 렌더 루프 ─────────────────────────────────────────────────
let frameCount = 0;
const fpsEl = document.getElementById('fps-display');

// ── 본 마커 (디버그 구체) ─────────────────────────────────────

// 모델 머티리얼 원본 백업 (실루엣 전환용)
const _origMaterials = new Map();

function _setModelSilhouette(enabled) {
  if (!model) return;
  model.traverse((child) => {
    if (!child.isMesh) return;
    if (enabled) {
      // 원본 머티리얼 백업 후 반투명 처리
      if (!_origMaterials.has(child)) {
        _origMaterials.set(child, Array.isArray(child.material)
          ? child.material.map(m => m.clone())
          : child.material.clone());
      }
      const applyTransparent = (mat) => {
        mat.transparent = true;
        mat.opacity = 0.18;
        mat.depthWrite = false;
      };
      if (Array.isArray(child.material)) child.material.forEach(applyTransparent);
      else applyTransparent(child.material);
    } else {
      // 원본 머티리얼 복원
      if (_origMaterials.has(child)) {
        child.material = _origMaterials.get(child);
      }
    }
  });
}

window.ITDA_skeletonUpdatedThisFrame = false;

(function animate() {
  requestAnimationFrame(animate);
  const delta = clock.getDelta();

  mixer?.update(delta);
  controls.update();

  // 본 마커: visible인 것만 위치 추적
  for (const [boneName, sphere] of Object.entries(_boneMarkers)) {
    if (!sphere.visible) continue;
    const bone = bones[boneName]
      || bones['mixamorig:' + boneName]
      || bones['mixamorig' + boneName];
    if (bone) bone.getWorldPosition(sphere.position);
  }

  // 스켈레톤 모드이고 이번 프레임에 외부 MP/NPY 데이터로 업데이트가 없었다면
  // 아바타 실제 3D 본 위치로 스켈레톤을 갱신 (V3 JSON 모션 대응)
  if (skeletonGroup.visible && !window.ITDA_skeletonUpdatedThisFrame) {
    _updateSkeletonFromBones();
  }

  // 플래그 리셋은 render() 직전에 수행 (render 이후 리셋하면 다음 프레임 시작 전에
  // retargeting.js가 플래그를 세팅할 수 없어 타이밍 충돌 발생)
  window.ITDA_skeletonUpdatedThisFrame = false;
  renderer.render(scene, camera);

  if (fpsEl && ++frameCount % 10 === 0) {
    fpsEl.textContent = `FPS: ${(1 / delta).toFixed(0)}`;
  }
})();

// T-포즈 기준 상체 관절 위치 캐시 (머리/어깨/골반은 고정)
const _torsoRest = {
  head: null,
  leftShoulder: null,
  rightShoulder: null,
  leftHip: null,
  rightHip: null,
};
let _torsoRestCaptured = false;

function _captureTorsoRest(getBone) {
  const getPos = (name) => {
    const b = getBone(name);
    if (!b) return null;
    const v = new THREE.Vector3();
    b.getWorldPosition(v);
    return v;
  };
  _torsoRest.head = getPos('Head') || getPos('Neck') || getPos('Spine2');
  _torsoRest.leftShoulder = getPos('LeftUpperArm') || getPos('LeftShoulder');
  _torsoRest.rightShoulder = getPos('RightUpperArm') || getPos('RightShoulder');
  _torsoRest.leftHip = getPos('LeftUpLeg') || getPos('Hips');
  _torsoRest.rightHip = getPos('RightUpLeg') || getPos('Hips');
  _torsoRestCaptured = true;
}

function _updateSkeletonFromBones() {
  if (!model) return;

  // 세부 관절 연산 전 월드 매트릭스 강제 업데이트
  model.updateMatrixWorld(true);

  const getBone = (name) => {
    return bones[name]
      || bones['mixamorig:' + name]
      || bones['mixamorig' + name];
  };

  // 최초 1회 T-포즈 캡처
  if (!_torsoRestCaptured) {
    _captureTorsoRest(getBone);
  }

  const getJointPos = (boneName, out, parentBoneName) => {
    const b = getBone(boneName);
    if (b) {
      b.getWorldPosition(out);
      return true;
    }
    if (parentBoneName) {
      const pb = getBone(parentBoneName);
      if (pb) {
        pb.getWorldPosition(out);
        return true;
      }
    }
    out.set(0, 0, 0);
    return false;
  };

  const getTipPos = (boneName, parentName, out) => {
    const b = getBone(boneName);
    const p = getBone(parentName);
    if (b && p) {
      // 로컬 임시 벡터 — 전역 _tmpV1/V2 의존성 제거 (캐시 버전 호환)
      const lv1 = new THREE.Vector3();
      const lv2 = new THREE.Vector3();
      b.getWorldPosition(lv1);
      p.getWorldPosition(lv2);
      out.copy(lv1).add(lv1.clone().sub(lv2).multiplyScalar(0.8));
      return true;
    }
    if (b) {
      b.getWorldPosition(out);
      return true;
    }
    out.set(0, 0, 0);
    return false;
  };

  // 1. 왼손 관절 (0 ~ 20)
  getJointPos('LeftHand', _skJoints[0].position);
  _skJoints[0].visible = true;

  const leftFingers = [
    ['LeftHandThumb1', 'LeftHandThumb2', 'LeftHandThumb3'],
    ['LeftHandIndex1', 'LeftHandIndex2', 'LeftHandIndex3'],
    ['LeftHandMiddle1', 'LeftHandMiddle2', 'LeftHandMiddle3'],
    ['LeftHandRing1', 'LeftHandRing2', 'LeftHandRing3'],
    ['LeftHandPinky1', 'LeftHandPinky2', 'LeftHandPinky3']
  ];

  leftFingers.forEach((f, idx) => {
    const baseIdx = 1 + idx * 4;
    getJointPos(f[0], _skJoints[baseIdx].position, 'LeftHand');
    getJointPos(f[1], _skJoints[baseIdx + 1].position, f[0]);
    getJointPos(f[2], _skJoints[baseIdx + 2].position, f[1]);
    getTipPos(f[2], f[1], _skJoints[baseIdx + 3].position);
    for (let k = 0; k < 4; k++) _skJoints[baseIdx + k].visible = true;
  });

  // 2. 오른손 관절 (21 ~ 41)
  getJointPos('RightHand', _skJoints[21].position);
  _skJoints[21].visible = true;

  const rightFingers = [
    ['RightHandThumb1', 'RightHandThumb2', 'RightHandThumb3'],
    ['RightHandIndex1', 'RightHandIndex2', 'RightHandIndex3'],
    ['RightHandMiddle1', 'RightHandMiddle2', 'RightHandMiddle3'],
    ['RightHandRing1', 'RightHandRing2', 'RightHandRing3'],
    ['RightHandPinky1', 'RightHandPinky2', 'RightHandPinky3']
  ];

  rightFingers.forEach((f, idx) => {
    const baseIdx = 22 + idx * 4;
    getJointPos(f[0], _skJoints[baseIdx].position, 'RightHand');
    getJointPos(f[1], _skJoints[baseIdx + 1].position, f[0]);
    getJointPos(f[2], _skJoints[baseIdx + 2].position, f[1]);
    getTipPos(f[2], f[1], _skJoints[baseIdx + 3].position);
    for (let k = 0; k < 4; k++) _skJoints[baseIdx + k].visible = true;
  });

  // 3. 상체 포즈 관절 — 머리·어깨·골반은 T-포즈 위치 고정, 팔꿈치·손목만 모션 추적

  // 머리 (42): T-포즈 캐시 사용
  if (_torsoRest.head) {
    _skJoints[42].position.copy(_torsoRest.head);
    _skJoints[42].visible = true;
  } else {
    _skJoints[42].visible = false;
  }
  for (let i = 43; i <= 52; i++) _skJoints[i].visible = false;

  // 어깨 (53, 54): T-포즈 캐시 고정
  if (_torsoRest.leftShoulder) {
    _skJoints[53].position.copy(_torsoRest.leftShoulder);
    _skJoints[53].visible = true;
  } else { _skJoints[53].visible = false; }

  if (_torsoRest.rightShoulder) {
    _skJoints[54].position.copy(_torsoRest.rightShoulder);
    _skJoints[54].visible = true;
  } else { _skJoints[54].visible = false; }

  // 팔꿈치·손목 (55~58): 실제 모션 bone 위치로 업데이트
  const ok55 = getJointPos('LeftForeArm', _skJoints[55].position, 'LeftUpperArm');
  const ok56 = getJointPos('RightForeArm', _skJoints[56].position, 'RightUpperArm');
  const ok57 = getJointPos('LeftHand', _skJoints[57].position, 'LeftForeArm');
  const ok58 = getJointPos('RightHand', _skJoints[58].position, 'RightForeArm');
  _skJoints[55].visible = ok55;
  _skJoints[56].visible = ok56;
  _skJoints[57].visible = ok57;
  _skJoints[58].visible = ok58;

  // 59~64 숨김
  for (let i = 59; i <= 64; i++) _skJoints[i].visible = false;

  // 골반 (65, 66): T-포즈 캐시 고정
  if (_torsoRest.leftHip) {
    _skJoints[65].position.copy(_torsoRest.leftHip);
    _skJoints[65].visible = true;
  } else { _skJoints[65].visible = false; }

  if (_torsoRest.rightHip) {
    _skJoints[66].position.copy(_torsoRest.rightHip);
    _skJoints[66].visible = true;
  } else { _skJoints[66].visible = false; }

  // 67~74 숨김 (다리)
  for (let i = 67; i <= 74; i++) _skJoints[i].visible = false;

  // 연결 실린더(본) 갱신
  _allC.forEach((c, idx) => {
    const a = _skJoints[c[0]], b = _skJoints[c[1]];
    if (a.visible && b.visible) {
      const d = a.position.distanceTo(b.position);
      _skBones[idx].visible = true;
      _skBones[idx].position.copy(a.position).add(b.position).multiplyScalar(0.5);
      _skBones[idx].scale.set(1, d, 1);
      _skBones[idx].quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.position.clone().sub(a.position).normalize());
    } else {
      _skBones[idx].visible = false;
    }
  });
}

function _updateSkeleton(frameData) {
  // 스켈레톤 모드가 아닐 때는 처리하지 않음
  if (!skeletonGroup.visible) return;
  if (!frameData || frameData.length < 225) return;
  window.ITDA_skeletonUpdatedThisFrame = true;
  const A = 0.45;
  for (let i = 0; i < 75; i++) {
    const rx = frameData[i * 3], ry = frameData[i * 3 + 1], rz = frameData[i * 3 + 2];
    if (rx === 0 && ry === 0) { _skJoints[i].visible = false; continue; }
    _skJoints[i].visible = true;
    const tx = (rx - 0.5) * 1.8, ty = (0.5 - ry) * 1.8 + 1.2, tz = -rz * 1.5;
    _skJoints[i].position.x += (tx - _skJoints[i].position.x) * A;
    _skJoints[i].position.y += (ty - _skJoints[i].position.y) * A;
    _skJoints[i].position.z += (tz - _skJoints[i].position.z) * A;
  }
  _allC.forEach((c, idx) => {
    const a = _skJoints[c[0]], b = _skJoints[c[1]];
    if (a.visible && b.visible) {
      const d = a.position.distanceTo(b.position);
      _skBones[idx].visible = true;
      _skBones[idx].position.copy(a.position).add(b.position).multiplyScalar(0.5);
      _skBones[idx].scale.set(1, d, 1);
      _skBones[idx].quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.position.clone().sub(a.position).normalize());
    } else { _skBones[idx].visible = false; }
  });
}

function _setViewMode(mode) {
  // 본 마커 항상 숨김 (디버그 구체)
  Object.values(_boneMarkers).forEach(s => { s.visible = false; });

  // [NEW] 뷰 모드 토글 버튼 UI 시각적 피드백 대응
  const btnAvatar = document.getElementById('btn-view-avatar');
  const btnSkeleton = document.getElementById('btn-view-skeleton');
  if (btnAvatar && btnSkeleton) {
    if (mode === 'skeleton') {
      btnAvatar.style.background = 'rgba(124,58,237,0.2)';
      btnAvatar.style.border = '1px solid rgba(124,58,237,0.5)';
      btnAvatar.style.color = '#7c3aed';

      btnSkeleton.style.background = 'rgba(0,230,160,0.85)';
      btnSkeleton.style.border = '1px solid #00e6a0';
      btnSkeleton.style.color = '#fff';
    } else {
      btnAvatar.style.background = 'rgba(124,58,237,0.85)';
      btnAvatar.style.border = '1px solid #7c3aed';
      btnAvatar.style.color = '#fff';

      btnSkeleton.style.background = 'rgba(0,230,160,0.2)';
      btnSkeleton.style.border = '1px solid rgba(0,230,160,0.5)';
      btnSkeleton.style.color = '#00e6a0';
    }
  }

  // 카메라 위치 저장 (스켈레톤→아바타 복귀 시 복원용)
  let _savedCameraPos = null;
  let _savedCameraTarget = null;

  if (mode === 'skeleton') {
    // 아바타 모델 완전 숨김
    if (model) model.visible = false;
    skeletonGroup.visible = true;

    // 현재 카메라 위치 저장 후 전신 보이도록 뒤로 이동
    _setViewMode._savedPos = camera.position.clone();
    _setViewMode._savedTarget = controls.target.clone();
    // 스켈레톤 모드에서 전체가 더 잘 보이도록 카메라 거리 증가
    camera.position.set(0, 1.0, 3.8);
    camera.lookAt(0, 1.0, 0);
    controls.target.set(0, 1.0, 0);
    controls.update();
  } else {
    // 아바타 모드: 모델 다시 표시
    if (model) {
      model.visible = true;
      _setModelSilhouette(false);
    }
    // 스켈레톤 숨김
    _skJoints.forEach(j => { j.visible = false; });
    _skBones.forEach(b => { b.visible = false; });
    skeletonGroup.visible = false;

    // 저장된 카메라 위치 복원 (없으면 기본값)
    if (_setViewMode._savedPos) {
      camera.position.copy(_setViewMode._savedPos);
      controls.target.copy(_setViewMode._savedTarget);
      controls.update();
      _setViewMode._savedPos = null;
      _setViewMode._savedTarget = null;
    }
  }
}

// ── 공개 인터페이스 ───────────────────────────────────────────
window.ITDAAvatar5 = {
  updateSkeleton: _updateSkeleton,
  setViewMode: _setViewMode,
  setMorphTarget(name, value) {
    if (!headMesh) return;
    let idx = morphIndex[name];
    if (idx === undefined) {
      const cap = name.charAt(0).toUpperCase() + name.slice(1);
      idx = morphIndex[cap];
    }
    if (idx !== undefined) {
      headMesh.morphTargetInfluences[idx] = THREE.MathUtils.clamp(value, 0, 1);
    }
  },

  updateBone(boneName, rotation, alpha = 0.45) {
    const bone = bones[boneName]
      || bones['mixamorig:' + boneName]
      || bones['mixamorig' + boneName];
    if (!bone) return;

    // 뼈 이름(Side 제외)으로 제약 조건 검색
    const baseName = boneName.replace(/^(Left|Right|mixamorig:|mixamorig)/, '');
    const limit = BONE_CONSTRAINTS[baseName];

    if (rotation.w !== undefined) {
      // [Step 5 보완] 쿼터니언 방식에도 해부학적 제약 조건 적용
      if (limit) {
        // 임시 오일러 각도로 변환하여 제한 적용
        const euler = new THREE.Euler().setFromQuaternion(rotation, 'XYZ');
        if (limit.x) euler.x = THREE.MathUtils.clamp(euler.x, limit.x[0], limit.x[1]);
        if (limit.y) euler.y = THREE.MathUtils.clamp(euler.y, limit.y[0], limit.y[1]);
        if (limit.z) euler.z = THREE.MathUtils.clamp(euler.z, limit.z[0], limit.z[1]);
        bone.quaternion.slerp(new THREE.Quaternion().setFromEuler(euler), alpha);
      } else {
        bone.quaternion.slerp(rotation, alpha);
      }
    } else {
      // [Step 5] 오일러 방식 해부학적 제약 조건 적용
      let tx = rotation.x, ty = rotation.y, tz = rotation.z;

      if (limit) {
        if (limit.x) tx = THREE.MathUtils.clamp(tx, limit.x[0], limit.x[1]);
        if (limit.y) ty = THREE.MathUtils.clamp(ty, limit.y[0], limit.y[1]);
        if (limit.z) tz = THREE.MathUtils.clamp(tz, limit.z[0], limit.z[1]);
      }

      bone.rotation.x = THREE.MathUtils.lerp(bone.rotation.x, tx, alpha);
      bone.rotation.y = THREE.MathUtils.lerp(bone.rotation.y, ty, alpha);
      bone.rotation.z = THREE.MathUtils.lerp(bone.rotation.z, tz, alpha);
    }
  },

  addBoneMarker(boneName, color) {
    if (_boneMarkers[boneName]) return;
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(0.04, 8, 8),
      new THREE.MeshBasicMaterial({ color, depthTest: false }),
    );
    sphere.renderOrder = 999;
    scene.add(sphere);
    _boneMarkers[boneName] = sphere;
  },

  reset() {
    for (const [name, bone] of Object.entries(bones)) {
      const initial = initialBoneQuats[name];
      if (initial) bone.quaternion.copy(initial);
    }
    if (headMesh) headMesh.morphTargetInfluences?.fill(0);
  },

  // [Debug] Idle 등 AnimationMixer 를 번역 재생 시 정지/재개할 수 있게 노출
  get mixer() { return mixer; },
  stopIdle() {
    mixer?.stopAllAction();
    console.info('[Avatar] Idle mixer 정지됨 (번역 재생 중 간섭 방지)');
  },

  get bones() { return bones; },
  get initialBoneQuats() { return initialBoneQuats; },
  get model() { return model; },
};
