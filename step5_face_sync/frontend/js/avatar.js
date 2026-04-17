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
scene.background = new THREE.Color(0x02040a); // 더 깊은 우주 공간 느낌
scene.fog = new THREE.FogExp2(0x02040a, 0.05); // FogExp2로 몽환적인 분위기 연출

// ── 카메라 ────────────────────────────────────────────────────
const camera = new THREE.PerspectiveCamera(42, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(0, 1.45, 1.8);

// ── 렌더러 ────────────────────────────────────────────────────
const canvas = document.querySelector('#three-canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;

// ── 컨트롤 ────────────────────────────────────────────────────
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.target.set(0, 1.45, 0);
controls.minDistance = 1.0;
controls.maxDistance = 8;
controls.update();

// ── 조명 [Cyborg Alpha v2.3 - 시네마틱 라이팅] ────────────────
// 키 라이트 (샴페인 골드 - 메인 광원)
const keyLight = new THREE.DirectionalLight(0xFFE4BC, 4.0);
keyLight.position.set(-2, 4, 5);
keyLight.castShadow = true;
scene.add(keyLight);

// 림 라이트 (청명한 사이안 - 실루엣 강조)
const rimLight = new THREE.PointLight(0x00D9FF, 3.5, 20);
rimLight.position.set(2, 5, -5);
scene.add(rimLight);

// 코어 발광원 (가슴 중앙)
const pointCyan = new THREE.PointLight(0x00FFFF, 2.5, 8);
pointCyan.position.set(0, 1.3, 0.5);
scene.add(pointCyan);

// 환경광 (은은한 보라빛 톤)
scene.add(new THREE.AmbientLight(0x1B1B3A, 1.2));

// ── 바닥 그리드 ───────────────────────────────────────────────
const grid = new THREE.GridHelper(20, 30, 0x1a1a2e, 0x1a1a2e);
grid.position.y = -0.01;
scene.add(grid);

// ── 내부 상태 ─────────────────────────────────────────────────
let model = null;
let mixer = null;
let headMesh = null;        // Morph Targets가 있는 메시
let bones = {};          // Bone 이름 → THREE.Bone
let morphIndex = {};          // 감정 이름 → morphTargetInfluences 인덱스

const clock = new THREE.Clock();

// ── 모델 URL (폴백 지원) ─────────────────────────────────────
const MODEL_URLS = [
  // 1순위: 사용자가 선택한 고해상도 모델
  'https://raw.githubusercontent.com/hmthanh/3d-human-model/main/TranThiNgocTham.glb',
  // 2순위: Three.js 공식 안정 휴머노이드 (반드시 로드됨)
  'https://threejs.org/examples/models/gltf/Xbot.glb',
];
const jstEl = document.getElementById('joint-status');

function loadModelWithFallback(urls, index = 0) {
  if (index >= urls.length) {
    console.error('[ITDA Avatar] 모든 모델 URL 로드 실패');
    return;
  }
  console.info(`[ITDA Avatar] 모델 로드 시도 (${index + 1}/${urls.length}):`, urls[index]);

  new GLTFLoader().load(
    urls[index],
    (gltf) => {
      model = gltf.scene;
      scene.add(model);

    // AnimationMixer (기본 대기 동작)
    mixer = new THREE.AnimationMixer(model);
    const idleClip = gltf.animations.find(a => a.name === 'Idle');
    if (idleClip) {
      mixer.clipAction(idleClip).play();
    }

    // [Cyborg Alpha v2.3] 범용 Organic PBR (모델 이름 무관 - 어떤 모델이든 작동)
    model.traverse((child) => {
      if (child.isMesh) {
        // 메시 이름을 콘솔에 출력 (뼈대 확인용)
        console.log('[Mesh]', child.name);

        // 기존 재질의 metalness로 관절/피부 판별 (범용)
        const origMat = child.material;
        const isMetallic = Array.isArray(origMat)
          ? origMat.some(m => m.metalness > 0.5)
          : origMat?.metalness > 0.5;

        // 눈/보석 판별 (투명하거나 emissive가 강한 경우)
        const isGem = child.name.toLowerCase().includes('eye')
          || child.name.toLowerCase().includes('gem')
          || child.name.toLowerCase().includes('iris');

        if (isGem) {
          // 사파이어 블루 보석 재질
          child.material = new THREE.MeshPhysicalMaterial({
            color: 0x00BFFF,
            roughness: 0.01,
            metalness: 0.0,
            ior: 1.76,
            transmission: 1.0,
            thickness: 1.5,
            emissive: 0x004488,
            emissiveIntensity: 2.0,
          });
        } else if (isMetallic) {
          // 앤틱 골드/샴페인 골드 관절 (SAM 메카닉 느낌)
          child.material = new THREE.MeshPhysicalMaterial({
            color: 0xD4AF37, 
            metalness: 1.0,
            roughness: 0.15,
            clearcoat: 1.0,
            clearcoatRoughness: 0.1,
            emissive: 0x442200,
            emissiveIntensity: 0.5,
          });
          child.material.name = 'SAM_Metal';
        } else {
          // 프리미엄 화이트 세라믹 피부 (반디 스타일)
          child.material = new THREE.MeshPhysicalMaterial({
            color: 0xF8F8FF,
            metalness: 0.05,
            roughness: 0.08,
            ior: 1.45,
            transmission: 0.05,
            thickness: 0.8,
            attenuationColor: new THREE.Color(1.0, 0.5, 0.4),
            subsurfaceIntensity: 1.0,
            specularIntensity: 0.8,
          });
        }

        // 모프 타겟 감지 (가장 많은 블렌드쉐입을 가진 메시를 헤드로 지정)
        if (child.morphTargetDictionary) {
          const count = Object.keys(child.morphTargetDictionary).length;
          const currentCount = headMesh ? Object.keys(morphIndex).length : 0;
          if (count > currentCount) {
            headMesh = child;
            morphIndex = child.morphTargetDictionary;
            console.info('[ITDA Avatar] Head Mesh:', child.name, '/ Morphs:', count);
          }
        }
      }
      if (child.isBone) {
        bones[child.name] = child;
      }
    });

    console.info('[ITDA Avatar] Cyborg Alpha v2.3 Universal Specs Applied. Bones:', Object.keys(bones).length);
    console.info('[ITDA Avatar] Bone Names:', Object.keys(bones).join(', '));
    window.dispatchEvent(new CustomEvent('itda:avatar:ready'));
    },
    // 로딩 진행률
    (xhr) => {
      if (xhr.total > 0) {
        const pct = Math.round(xhr.loaded / xhr.total * 100);
        if (jstEl) jstEl.textContent = `모델 로딩 중... ${pct}%`;
      }
    },
    // 로드 실패 → 다음 폴백 URL로 자동 재시도
    (err) => {
      console.warn(`[ITDA Avatar] 로드 실패 (${urls[index]}):`, err.message);
      loadModelWithFallback(urls, index + 1);
    }
  );
}

// 모델 로딩 시작 (폴백 포함)
loadModelWithFallback(MODEL_URLS);

// Fiber Optics Pulse
let pulseSpeed = 0.8;
let pulseColor = new THREE.Color(0x00BFFF);

// ── 렌더 루프 (Cinematic Post-Process v2.1) ───────────────────
(function animate() {
  requestAnimationFrame(animate);
  const delta = clock.getDelta();
  const time = clock.getElapsedTime();

  mixer?.update(delta);
  controls.update();

  // [SAM Aesthetic Engine] 실시간 컬러 및 발광 맥동 제어
  const pulse = 1.5 + Math.sin(time * pulseSpeed * Math.PI) * 1.5;
  rimLight.intensity = 2.0 + Math.sin(time * 0.5) * 1.0;
  pointCyan.intensity = pulse;

  // 모든 금속 재질에 은은한 글로우 효과 전이
  model?.traverse((child) => {
    if (child.isMesh && child.material.name === 'SAM_Metal') {
      child.material.emissiveIntensity = 0.5 + Math.sin(time * 2) * 0.4;
    }
  });

  renderer.render(scene, camera);
})();

// ── 반응형 리사이즈 핸들러 ──────────────────────────────────────
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// ── 공개 인터페이스 ───────────────────────────────────────────
window.ITDAAvatar5 = {
  /**
   * 전용 Morph Target 설정 (이름 기반 범용 설정)
   * @param {string} name  - ARKit 표준 이름 (예: mouthPucker, browInnerUp)
   * @param {number} value - 0.0 ~ 1.0
   */
  setMorphTarget(name, value) {
    if (!headMesh) return;

    // 모델의 Morph Target 이름에서 대소문자 구분 없이 매칭 시도
    let idx = morphIndex[name];
    if (idx === undefined) {
      // 첫 글자 대문자 변환 시도 (예: mouthPucker -> MouthPucker)
      const capitalized = name.charAt(0).toUpperCase() + name.slice(1);
      idx = morphIndex[capitalized];
    }

    if (idx !== undefined) {
      headMesh.morphTargetInfluences[idx] = THREE.MathUtils.clamp(value, 0, 1);
    }
  },

  /**
   * Bone 회전 업데이트 (수어 전용 고속 Lerp 적용)
   */
  updateBone(boneName, rotation, alpha = 0.2) {
    const bone = bones[boneName];
    if (!bone) return;

    // 짐벌 락(Gimbal Lock) 방지를 위해 오일러 각도 제한 및 부드러운 보간
    bone.rotation.x = THREE.MathUtils.lerp(bone.rotation.x, rotation.x, alpha);
    bone.rotation.y = THREE.MathUtils.lerp(bone.rotation.y, rotation.y, alpha);
    bone.rotation.z = THREE.MathUtils.lerp(bone.rotation.z, rotation.z, alpha);
  },

  updateFiberPulse(speed, colorHex) {
    pulseSpeed = speed;
    pulseColor.setHex(parseInt(colorHex.replace('#', '0x')));
  },

  reset() {
    for (const bone of Object.values(bones)) bone.rotation.set(0, 0, 0);
    if (headMesh) headMesh.morphTargetInfluences.fill(0);
  },
  bones,
};
