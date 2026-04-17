/**
 * avatar.js [Cyborg Alpha v2.6 Full Feature Edition]
 */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

console.info('%c[ITDA Avatar] >>> Restoring All Features...', 'background: #00BFFF; color: #000; font-weight: bold; padding: 2px 5px;');

// ── 환경 설정 (White Theme) ───────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xffffff);
scene.fog = new THREE.FogExp2(0xffffff, 0.05);

const camera = new THREE.PerspectiveCamera(42, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(0, 1.45, 1.8);

const canvas = document.querySelector('#three-canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.target.set(0, 1.45, 0);

// ── 조명 ──────────────────────────────────────────────────
const keyLight = new THREE.DirectionalLight(0xFFE4BC, 3.5);
keyLight.position.set(-2, 4, 5);
scene.add(keyLight);
scene.add(new THREE.AmbientLight(0xFFFFFF, 0.8)); // 화이트 배경에 맞게 광량 업

// ── 상태 및 기능 변수 ─────────────────────────────────────
let model = null;
let mixer = null;
let headMesh = null;
let bones = {};
let morphIndex = {};
const clock = new THREE.Clock();

// 절차적 애니메이션 변수 
let breathPhase = 0;
let blinkTimer = 0;
let nextBlinkTime = 2000;
let fiberPhase = 0;
let fiberSpeed = 0.8;
let fiberColor = new THREE.Color(0x00BFFF);

const MODEL_URLS = [
  'https://raw.githubusercontent.com/hmthanh/3d-human-model/main/TranThiNgocTham.glb',
  'https://threejs.org/examples/models/gltf/Xbot.glb',
];

// ── 로딩 엔진 (Robust Edition) ───────────────────────────
function loadModelWithFallback(urls, index = 0) {
  if (index >= urls.length) return;
  console.log(`[ITDA Avatar] Loading: ${urls[index]}`);

  new GLTFLoader().load(urls[index], (gltf) => {
    model = gltf.scene;
    scene.add(model);
    mixer = new THREE.AnimationMixer(model);

    model.traverse((child) => {
      if (child.isMesh) {
        child.castShadow = true;
        child.receiveShadow = true;
        if (child.morphTargetDictionary) {
          headMesh = child;
          morphIndex = child.morphTargetDictionary;
        }
      }
      if (child.isBone) {
        // [Cyborg Alpha] 초기 자세 캡처 및 보정 기준점 저장
        child.initialQuaternion = child.quaternion.clone();
        bones[child.name] = child;
      }
    });

    try { window.ITDARetargeting5?.clearArmBoneCache(); } catch(e){}
    analyzeSkeleton(bones);
    window.dispatchEvent(new CustomEvent('itda:avatar:ready'));
  }, null, (err) => loadModelWithFallback(urls, index + 1));
}

function analyzeSkeleton(bones) {
  const names = Object.keys(bones);
  console.group('%c[ITDA Rig Report]', 'background: #000; color: #FFF; font-weight: bold;');
  
  const criticals = [
    { label: 'SHOULDER', keys: ['Shoulder', 'Clavicle', 'Collar'] },
    { label: 'ARM_UP', keys: ['Arm', 'UpperArm'] },
    { label: 'ARM_LOW', keys: ['ForeArm', 'LowerArm', 'Forearm'] },
    { label: 'HAND', keys: ['Hand', 'Wrist'] },
    { label: 'SPINE', keys: ['Spine', 'Base'] }
  ];

  const container = document.getElementById('rig-items-container');
  if (container) container.innerHTML = '';

  criticals.forEach(c => {
    ['Left', 'Right'].forEach(side => {
      const boneName = fuzzyFindDebug(bones, side, c.keys);
      const sideChar = side === 'Left' ? 'L' : 'R';
      const label = `${c.label}_${sideChar}`;
      
      console.log(`${label}:`, boneName ? `%c[OK] ${boneName}` : `%c[MISSING]`, boneName ? 'color: #00FF00' : 'color: #FF0000');
      
      if (container) {
        const item = document.createElement('div');
        item.className = 'rig-item';
        const colorClass = boneName ? 'rig-ok' : 'rig-missing';
        item.innerHTML = `<span>${label}</span><span class="${colorClass}">${boneName ? 'OK' : 'MISSING'}</span>`;
        container.appendChild(item);
      }
    });
  });
  console.groupEnd();
  window.ITDAAvatarBones = bones;
}

// 지능형 매핑 보조 함수 (정규식 지원)
function fuzzyFindDebug(bones, side, candidates) {
  const names = Object.keys(bones);
  const sideAlt = side === 'Right' ? 'R' : 'L';
  const sideFull = side.toLowerCase();

  for (const c of candidates) {
    const variants = [
      `${side}${c}`, `mixamorig${side}${c}`, `${side}_${c}`, 
      `${sideAlt}_${c}`, `${c}_${sideAlt}`, `${c}.${sideAlt}`,
      `${sideFull}_${c}`, `${c}_${sideFull}`
    ];
    for (const v of variants) {
      const found = names.find(n => n.toLowerCase() === v.toLowerCase());
      if (found) return found;
    }
  }
  return names.find(n => {
    const lower = n.toLowerCase();
    return (lower.includes(sideFull) || lower.includes(`_${sideAlt.toLowerCase()}`)) 
           && candidates.some(c => lower.includes(c.toLowerCase()));
  });
}

// ── 절차적 기능 (Idle Animation) ──────────────────────────
function updateIdleContent(delta, time) {
  if (!model) return;

  // 1. 호흡 (Breathing)
  breathPhase += delta * 1.5;
  const breathFactor = Math.sin(breathPhase) * 0.015;
  const spine = bones['Spine2'] || bones['spine003'] || bones['Spine'];
  if (spine) spine.rotation.x += breathFactor * 0.1;
  
  // 2. 눈깜빡임 (Blinking)
  if (headMesh && (morphIndex['eyeBlinkLeft'] || morphIndex['Eyes_Closed'])) {
    blinkTimer += delta * 1000;
    if (blinkTimer > nextBlinkTime) {
      const blinkIdxL = morphIndex['eyeBlinkLeft'] || morphIndex['Eyes_Closed'];
      const blinkIdxR = morphIndex['eyeBlinkRight'] || morphIndex['Eyes_Closed'];
      const duration = 150; 
      const progress = (blinkTimer - nextBlinkTime) / duration;
      
      if (progress <= 1.0) {
        const val = Math.sin(progress * Math.PI);
        headMesh.morphTargetInfluences[blinkIdxL] = val;
        headMesh.morphTargetInfluences[blinkIdxR] = val;
      } else {
        blinkTimer = 0;
        nextBlinkTime = 2000 + Math.random() * 4000;
      }
    }
  }

  // 3. 미세 흔들림 (Micro Sway)
  const neck = bones['Neck'] || bones['neck'];
  if (neck) {
    neck.rotation.y = Math.sin(time * 0.5) * 0.05;
    neck.rotation.z = Math.cos(time * 0.3) * 0.02;
  }
}

// ── 루프 ──────────────────────────────────────────────────────
function animate() {
  requestAnimationFrame(animate);
  const delta = clock.getDelta();
  const time = clock.getElapsedTime();

  updateIdleContent(delta, time);
  mixer?.update(delta);
  controls.update();
  renderer.render(scene, camera);
}
animate();

// ── 공개 인터페이스 ───────────────────────────────────────────
window.ITDAAvatar5 = {
  setMorphTarget(name, value) {
    if (!headMesh) return;
    const idx = morphIndex[name];
    if (idx !== undefined) headMesh.morphTargetInfluences[idx] = value;
  },
  updateBone(boneName, rotation, alpha = 0.2) {
    const bone = bones[boneName];
    if (!bone) return;
    if (rotation.isQuaternion) bone.quaternion.slerp(rotation, alpha);
    else {
      bone.rotation.x = THREE.MathUtils.lerp(bone.rotation.x, rotation.x || 0, alpha);
      bone.rotation.y = THREE.MathUtils.lerp(bone.rotation.y, rotation.y || 0, alpha);
      bone.rotation.z = THREE.MathUtils.lerp(bone.rotation.z, rotation.z || 0, alpha);
    }
  },
  updateFiberPulse(hz, colorStr) {
    fiberSpeed = hz;
    fiberColor.set(colorStr);
    console.log('[ITDA Avatar] Fiber Pulse Sync:', hz, colorStr);
  },
  reset() {
    Object.values(bones).forEach(b => b.rotation.set(0, 0, 0));
  },
  bones
};

loadModelWithFallback(MODEL_URLS);
