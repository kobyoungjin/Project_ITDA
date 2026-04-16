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
import { GLTFLoader }    from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ── 씬 ───────────────────────────────────────────────────────
const scene    = new THREE.Scene();
scene.background = new THREE.Color(0x050810);
scene.fog        = new THREE.Fog(0x050810, 12, 50);

// ── 렌더러 및 카메라 초기화 ─────────────────────────────────────
const canvas   = document.querySelector('#three-canvas');
const container = document.querySelector('#app-container');

// 초기 사이즈 계산 (앱 컨테이너가 로딩 직후 크기가 0일 때 방어 로직)
const getAppSize = () => {
  let width = container ? container.clientWidth : window.innerWidth;
  let height = container ? container.clientHeight : window.innerHeight;
  if (width === 0) width = Math.min(window.innerWidth, 450);
  if (height === 0) height = window.innerHeight;
  return { width, height };
};

const initialSize = getAppSize();

const camera = new THREE.PerspectiveCamera(42, initialSize.width / initialSize.height, 0.1, 100);
camera.position.set(0, 1.6, 1.5); 

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(initialSize.width, initialSize.height);
renderer.shadowMap.enabled = true;
renderer.toneMapping       = THREE.ACESFilmicToneMapping;
renderer.outputColorSpace  = THREE.SRGBColorSpace;

// ── 컨트롤 (고정) ───────────────────────────────────────────
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 1.6, 0); 
// 사용자가 화면을 마우스로 조작하지 못하도록 기능 모두 비활성화
controls.enableZoom = false;
controls.enablePan = false;
controls.enableRotate = false;
controls.update();

// ── 조명 ──────────────────────────────────────────────────────
scene.add(new THREE.AmbientLight(0xffffff, 1.5)); 
const hemiLight = new THREE.HemisphereLight(0xffffff, 0x444444, 2.0);
hemiLight.position.set(0, 5, 0);
scene.add(hemiLight);

const dirLight = new THREE.DirectionalLight(0xffffff, 1.5);
dirLight.position.set(2, 5, 5);
dirLight.castShadow = true;
scene.add(dirLight);

const pointCyan   = new THREE.PointLight(0x00f2fe, 3.0, 15);
pointCyan.position.set(2, 3, 3);
scene.add(pointCyan);

const pointPurple = new THREE.PointLight(0x7000ff, 3.0, 15);
pointPurple.position.set(-2, 3, 3);
scene.add(pointPurple);

// ── 바닥 그리드 ───────────────────────────────────────────────
const grid = new THREE.GridHelper(20, 30, 0x1a1a2e, 0x1a1a2e);
grid.position.y = -0.01;
scene.add(grid);

// ── 내부 상태 ─────────────────────────────────────────────────
let model       = null;
let mixer       = null;
let headMesh    = null;        // Morph Targets가 있는 메시
let bones       = {};          // Bone 이름 → THREE.Bone
let initialBoneQuats = {};     // 모델의 원본 자세 저장 (쿼터니언 기반 안정적 복구)

const clock = new THREE.Clock();

// ── 모델 로딩 ─────────────────────────────────────────────────
const MODEL_URL = './models/female_human.glb';
const jstEl     = document.getElementById('joint-status');

new GLTFLoader().load(
  MODEL_URL,
  (gltf) => {
    model = gltf.scene;
    // 아바타 위치 조정
    model.scale.set(1.0, 1.0, 1.0);
    model.position.set(0, 0, 0); 
    scene.add(model);

    // Bone / Morph 수집 및 초기 자세 저장
    bones = {};
    initialBoneQuats = {};
    const morphMeshes = [];

    model.traverse((child) => {
      if (child.isBone) {
        bones[child.name] = child;
        // 원본 쿼터니언 복사 저장 (Euler보다 안정적)
        initialBoneQuats[child.name] = child.quaternion.clone();
      }
      if (child.isMesh && child.morphTargetDictionary) {
        morphMeshes.push(child);
      }
    });

    headMesh = morphMeshes;
    
    if (jstEl) jstEl.textContent = 'Joints: ACTIVE';
    const statusEl = document.getElementById('model-status');
    if (statusEl) {
      statusEl.textContent = '👩 Human (Female) — LOADED';
      statusEl.classList.add('loaded');
    }
    window.dispatchEvent(new CustomEvent('itda:avatar:ready'));
  },
  (xhr) => {
    const pct = ((xhr.loaded / xhr.total) * 100).toFixed(0);
    if (jstEl) jstEl.textContent = `로딩 ${pct}%`;
  },
  (err) => console.error('[ITDA Avatar] 로드 실패:', err),
);

// 카메라 구도 최적화 (상체와 얼굴이 잘 보이도록 조절)
camera.position.set(0, 1.4, 2.8); 
controls.target.set(0, 1.1, 0); 
controls.update();

window.addEventListener('resize', () => {
  const { width, height } = getAppSize();
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
});
setTimeout(() => window.dispatchEvent(new Event('resize')), 100);

// ── 렌더 루프 ─────────────────────────────────────────────────
let frameCount = 0;
const fpsEl    = document.getElementById('fps-display');

(function animate() {
  requestAnimationFrame(animate);
  const delta = clock.getDelta();
  mixer?.update(delta);
  controls.update();
  renderer.render(scene, camera);

  if (fpsEl && ++frameCount % 10 === 0) {
    fpsEl.textContent = `FPS: ${(1 / delta).toFixed(0)}`;
  }
})();

// ── 공개 인터페이스 ───────────────────────────────────────────
window.ITDAAvatar5 = {
  setMorphTarget(name, value) {
    if (!headMesh) return;
    const mapping = {
      'Angry':     ['browDownLeft', 'browDownRight', 'noseSneerLeft', 'noseSneerRight'],
      'Surprised': ['jawOpen', 'eyeWideLeft', 'eyeWideRight'],
      'Sad':       ['mouthFrownLeft', 'mouthFrownRight', 'browInnerUp']
    };
    const targets = mapping[name] || [name];
    headMesh.forEach(mesh => {
      targets.forEach(tName => {
        const idx = mesh.morphTargetDictionary[tName];
        if (idx !== undefined) {
          mesh.morphTargetInfluences[idx] = THREE.MathUtils.clamp(value, 0, 1);
        }
      });
    });
  },

  /**
   * Bone 업데이트 (Euler 또는 Quaternion 지원)
   * @param {string} boneName 
   * @param {Object} rotation - {x,y,z} (Euler) 또는 {x,y,z,w} (Quaternion)
   * @param {number} alpha - Lerp 강도
   */
  updateBone(boneName, rotation, alpha = 0.2) {
    const bone = bones[boneName] || bones['mixamorig' + boneName]; 
    if (!bone) return;

    if (rotation.w !== undefined) {
      // Quaternion 모드 (Slerp)
      bone.quaternion.slerp(rotation, alpha);
    } else {
      // Euler 모드 (Lerp)
      bone.rotation.x = THREE.MathUtils.lerp(bone.rotation.x, rotation.x, alpha);
      bone.rotation.y = THREE.MathUtils.lerp(bone.rotation.y, rotation.y, alpha);
      bone.rotation.z = THREE.MathUtils.lerp(bone.rotation.z, rotation.z, alpha);
    }
  },

  /** 아바타를 모델 로드 당시의 '원본 기본 자세'로 리셋 */
  reset() {
    for (const [name, bone] of Object.entries(bones)) {
      const initial = initialBoneQuats[name];
      if (initial) {
        bone.quaternion.copy(initial);
      }
    }
    if (headMesh) {
      headMesh.forEach(mesh => mesh.morphTargetInfluences.fill(0));
    }
  },

  bones,
  initialBoneQuats,
};
