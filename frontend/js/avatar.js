/**
 * avatar.js  ─  Step 5: Three.js RobotExpressive 아바타 씬
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ── 해부학적 제약 조건 (BONE_CONSTRAINTS) ─────────────────────
const BONE_CONSTRAINTS = {
  Shoulder: { y: [-0.2, 0.2], z: [-0.15, 0.15] },
  Arm:      { z: [-Math.PI, Math.PI / 2] },
  UpperArm: { z: [-Math.PI, Math.PI / 2] },
  ForeArm:  { x: [0, Math.PI * 0.8] },
  Hand:     { x: [-0.5, 0.5], y: [-0.5, 0.5] },
  Thumb1:   { x: [-0.3, 0.3], y: [-0.3, 0.6] },
  Thumb2:   { x: [0, 0.5] },
  Thumb3:   { x: [0, 0.5] },
  Index1:   { x: [0, 1.5] },
  Index2:   { x: [0, 1.5] },
  Index3:   { x: [0, 1.5] },
  Middle1:  { x: [0, 1.5] },
  Middle2:  { x: [0, 1.5] },
  Middle3:  { x: [0, 1.5] },
  Ring1:    { x: [0, 1.5] },
  Ring2:    { x: [0, 1.5] },
  Ring3:    { x: [0, 1.5] },
  Pinky1:   { x: [0, 1.5] },
  Pinky2:   { x: [0, 1.5] },
  Pinky3:   { x: [0, 1.5] },
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
camera.position.set(0, 1.35, 1.5);

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

const clock = new THREE.Clock();

// ── 모델 URL (fallback 순서) ──────────────────────────────────
const MODEL_URLS = [
  './models/sonyr.glb',
  './models/ITDAModel.glb',
  'https://raw.githubusercontent.com/hmthanh/3d-human-model/main/TranThiNgocTham.glb',
  'https://threejs.org/examples/models/gltf/RobotExpressive/RobotExpressive.glb',
];
const jstEl = document.getElementById('joint-status');

function loadModelWithFallback(urls, index = 0) {
  if (index >= urls.length) {
    console.error('[ITDA Avatar] 모든 모델 URL 로드 실패');
    return;
  }
  console.info(`[ITDA Avatar] 모델 로드 시도 (${index + 1}/${urls.length}):`, urls[index]);
  if (jstEl) jstEl.textContent = `모델 로딩 중... (${index + 1}/${urls.length})`;

  new GLTFLoader().load(
    urls[index],
    (gltf) => {
      model = gltf.scene;
      // 일부 GLB 모델이 상하반전으로 로드되는 경우 보정
      ///model.rotation.x = Math.PI;
      scene.add(model);

      mixer = new THREE.AnimationMixer(model);
      const idleClip = gltf.animations.find(a => a.name === 'Idle');
      if (idleClip) mixer.clipAction(idleClip).play();

      // 뼈/모프 수집 (재질은 GLB 원본 그대로 사용)
      model.traverse((child) => {
        if (child.isMesh) {
          console.log('[Mesh]', child.name);

          // 모프 타겟 — 가장 많은 블렌드쉐입을 가진 메시를 헤드로 지정
          if (child.morphTargetDictionary) {
            const count = Object.keys(child.morphTargetDictionary).length;
            const currentCount = Object.keys(morphIndex).length;
            if (count > currentCount) {
              headMesh = child;
              morphIndex = child.morphTargetDictionary;
              console.info('[ITDA Avatar] Head Mesh:', child.name, '/ Morphs:', count);
            }
          }
        }

        if (child.isBone) {
          bones[child.name] = child;
          initialBoneQuats[child.name] = child.quaternion.clone();
        }
      });

      if (jstEl) jstEl.textContent = 'Joints: ACTIVE';
      const statusEl = document.getElementById('model-status');
      if (statusEl) {
        statusEl.textContent = `✅ 모델 로드 완료 (${index + 1}순위)`;
        statusEl.classList.add('loaded');
      }
      console.info('[ITDA Avatar] 로드 완료:', urls[index], '/ 뼈:', Object.keys(bones).length);
      window.dispatchEvent(new CustomEvent('itda:avatar:ready'));
    },
    (xhr) => {
      if (xhr.total > 0 && jstEl)
        jstEl.textContent = `모델 로딩 중... ${Math.round(xhr.loaded / xhr.total * 100)}%`;
    },
    (err) => {
      console.warn('[ITDA Avatar] 로드 실패, 다음 fallback 시도:', urls[index], err.message);
      loadModelWithFallback(urls, index + 1);
    }
  );
}

loadModelWithFallback(MODEL_URLS);

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
const _boneMarkers = {};

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

  renderer.render(scene, camera);

  if (fpsEl && ++frameCount % 10 === 0) {
    fpsEl.textContent = `FPS: ${(1 / delta).toFixed(0)}`;
  }
})();

// ── 스켈레톤 뷰 (Streamlit 이식) ─────────────────────────────
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
  m.visible = false; // 초기에는 숨김
  skeletonGroup.add(m);
  _skJoints.push(m);
}

const _HC = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]];
const _PC = [[11,12],[11,13],[13,15],[12,14],[14,16],[11,23],[12,24],[23,24],[23,25],[25,27],[24,26],[26,28]];
const _allC = [];
_HC.forEach(c => _allC.push([c[0],c[1]]));
_HC.forEach(c => _allC.push([c[0]+21,c[1]+21]));
_PC.forEach(c => _allC.push([c[0]+42,c[1]+42]));
_allC.push([57,0]); _allC.push([58,21]);

_allC.forEach(() => {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(0.005,0.005,1,6), _bMat);
  skeletonGroup.add(m);
  _skBones.push(m);
});

function _updateSkeleton(frameData) {
  if (!frameData || frameData.length < 225) return;
  const A = 0.45;
  for (let i = 0; i < 75; i++) {
    const rx = frameData[i*3], ry = frameData[i*3+1], rz = frameData[i*3+2];
    if (rx === 0 && ry === 0) { _skJoints[i].visible = false; continue; }
    _skJoints[i].visible = true;
    const tx = (rx-0.5)*1.8, ty = (0.5-ry)*1.8+1.2, tz = -rz*1.5;
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
      _skBones[idx].quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), b.position.clone().sub(a.position).normalize());
    } else { _skBones[idx].visible = false; }
  });
}

function _setViewMode(mode) {
  // 본 마커 항상 숨김 (디버그 구체)
  Object.values(_boneMarkers).forEach(s => { s.visible = false; });

  if (mode === 'skeleton') {
    // 아바타 완전히 숨김 — 뼈대만 표시
    if (model) {
      _setModelSilhouette(false); // 머티리얼 복원 후
      model.visible = false;      // 완전히 숨김
    }
    skeletonGroup.visible = true;
    // 전신이 보이도록 카메라 후퇴
    camera.position.set(0, 1.0, 4.5);
    camera.lookAt(0, 1.0, 0);
    controls.target.set(0, 1.0, 0);
    controls.update();
  } else {
    // 아바타 모드: 원본 머티리얼로 모델 복원
    if (model) {
      model.visible = true;
      _setModelSilhouette(false);
    }
    // 스켈레톤 완전히 숨김
    _skJoints.forEach(j => { j.visible = false; });
    _skBones.forEach(b => { b.visible = false; });
    skeletonGroup.visible = false;
    // 상체 중심 카메라 복귀
    camera.position.set(0, 1.35, 1.5);
    camera.lookAt(0, 1.35, 0);
    controls.target.set(0, 1.35, 0);
    controls.update();
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
};
