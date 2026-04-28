/**
 * avatar.js  ─  Step 5: Three.js RobotExpressive 아바타 씬
 *
 * ■ 역할
 *   1. Three.js 씬, 카메라, 렌더러, 조명, 컨트롤 초기화
 *   2. RobotExpressive.glb 로드 (Head Morph Targets: Angry / Surprised / Sad)
 *   3. window.ITDAAvatar5 공개 인터페이스 제공
 *      - setMorphTarget(name, value) : 감정 Morph Target 설정 (0~1)
 *      - updateBone(name, rotation)  : 손/팔 Bone 업데이트 (Lerp)
 *
 * ■ 사용 라이브러리
 *   - Three.js r160 (importmap)
 *   - GLTFLoader, AnimationMixer
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

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

(function animate() {
  requestAnimationFrame(animate);
  const delta = clock.getDelta();

  mixer?.update(delta);
  controls.update();

  for (const [boneName, sphere] of Object.entries(_boneMarkers)) {
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

// ── 공개 인터페이스 ───────────────────────────────────────────
window.ITDAAvatar5 = {
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
    // mixamorig: 콜론 네이밍 포함 범용 탐색
    const bone = bones[boneName]
      || bones['mixamorig:' + boneName]
      || bones['mixamorig' + boneName];
    if (!bone) return;

    if (rotation.w !== undefined) {
      bone.quaternion.slerp(rotation, alpha);
    } else {
      bone.rotation.x = THREE.MathUtils.lerp(bone.rotation.x, rotation.x, alpha);
      bone.rotation.y = THREE.MathUtils.lerp(bone.rotation.y, rotation.y, alpha);
      bone.rotation.z = THREE.MathUtils.lerp(bone.rotation.z, rotation.z, alpha);
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
