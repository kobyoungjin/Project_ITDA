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

// ── 카메라 ────────────────────────────────────────────────────
const camera = new THREE.PerspectiveCamera(42, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(0, 1.45, 1.8);

// ── 렌더러 ────────────────────────────────────────────────────
const canvas   = document.querySelector('#three-canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.toneMapping       = THREE.ACESFilmicToneMapping;
renderer.outputColorSpace  = THREE.SRGBColorSpace;

// ── 컨트롤 ────────────────────────────────────────────────────
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.target.set(0, 1.45, 0);
controls.minDistance = 1.0;
controls.maxDistance = 8;
controls.update();

// ── 조명 ──────────────────────────────────────────────────────
scene.add(new THREE.AmbientLight(0xffffff, 0.6));

const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
dirLight.position.set(5, 10, 7.5);
dirLight.castShadow = true;
scene.add(dirLight);

const pointCyan   = new THREE.PointLight(0x00f2fe, 2.5, 12);
pointCyan.position.set(2, 2.5, 2);
scene.add(pointCyan);

const pointPurple = new THREE.PointLight(0x7000ff, 2.5, 12);
pointPurple.position.set(-2, 2.5, 1);
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
let morphIndex  = {};          // 감정 이름 → morphTargetInfluences 인덱스

const clock = new THREE.Clock();

// ── 모델 로딩 ─────────────────────────────────────────────────
const MODEL_URL = 'https://threejs.org/examples/models/gltf/RobotExpressive/RobotExpressive.glb';
const jstEl     = document.getElementById('joint-status');

new GLTFLoader().load(
  MODEL_URL,
  (gltf) => {
    model = gltf.scene;
    scene.add(model);

    // AnimationMixer (기본 대기 동작)
    mixer = new THREE.AnimationMixer(model);
    const idleClip = gltf.animations.find(a => a.name === 'Idle');
    if (idleClip) {
      mixer.clipAction(idleClip).play();
    }

    // Bone / Mesh 수집
    model.traverse((child) => {
      if (child.isBone) {
        bones[child.name] = child;
      }
      if (child.isMesh && child.morphTargetDictionary) {
        const names = Object.keys(child.morphTargetDictionary);
        if (names.includes('Angry') || names.includes('Surprised') || names.includes('Sad')) {
          headMesh   = child;
          morphIndex = child.morphTargetDictionary;
          console.info('[ITDA Avatar] Head MorphTargets:', names);
        }
      }
    });

    if (jstEl) jstEl.textContent = 'Joints: ACTIVE';
    document.getElementById('model-status')?.classList.add('loaded');
    window.dispatchEvent(new CustomEvent('itda:avatar:ready'));
    console.info('[ITDA Avatar] RobotExpressive 로드 완료');
  },
  (xhr) => {
    const pct = ((xhr.loaded / xhr.total) * 100).toFixed(0);
    if (jstEl) jstEl.textContent = `로딩 ${pct}%`;
  },
  (err) => {
    console.error('[ITDA Avatar] 모델 로드 실패:', err);
  },
);

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

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
  /**
   * 감정 Morph Target 설정 (Head 메시)
   * @param {string} name  - 'Angry' | 'Surprised' | 'Sad'
   * @param {number} value - 0.0 ~ 1.0
   */
  setMorphTarget(name, value) {
    if (!headMesh) return;
    const idx = morphIndex[name];
    if (idx === undefined) return;
    headMesh.morphTargetInfluences[idx] =
      THREE.MathUtils.clamp(value, 0, 1);
  },

  /**
   * Bone 회전 업데이트 (Lerp 적용)
   * @param {string} boneName   - Three.js Bone 이름
   * @param {{x,y,z}} rotation  - 목표 오일러 각도(rad)
   * @param {number} alpha      - Lerp 계수 (기본 0.2)
   */
  updateBone(boneName, rotation, alpha = 0.2) {
    const bone = bones[boneName];
    if (!bone) return;
    bone.rotation.x = THREE.MathUtils.lerp(bone.rotation.x, rotation.x, alpha);
    bone.rotation.y = THREE.MathUtils.lerp(bone.rotation.y, rotation.y, alpha);
    bone.rotation.z = THREE.MathUtils.lerp(bone.rotation.z, rotation.z, alpha);
  },

  /** 아바타를 기본 자세로 리셋 */
  reset() {
    for (const bone of Object.values(bones)) {
      bone.rotation.set(0, 0, 0);
    }
    if (headMesh) headMesh.morphTargetInfluences.fill(0);
  },

  bones,
};
