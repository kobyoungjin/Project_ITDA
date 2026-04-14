import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

/**
 * avatar.js - Three.js 3D 캐릭터 로딩 및 씬 관리
 */

let scene, camera, renderer, controls;
let model, skeleton, mixer;
let bones = {};

const MODEL_URL = 'https://threejs.org/examples/models/gltf/Xbot.glb';

function init() {
    // ── 씬 설정 ────────────────────────────────────────────────
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x050810);
    scene.fog = new THREE.Fog(0x050810, 10, 50);

    // ── 카메라 ────────────────────────────────────────────────
    camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 100);
    camera.position.set(0, 1.2, 3);

    // ── 렌더러 ────────────────────────────────────────────────
    const canvas = document.querySelector('#three-canvas');
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.toneMapping = THREE.ReinhardToneMapping;
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    // ── 컨트롤 ────────────────────────────────────────────────
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, 1.2, 0);
    controls.update();

    // ── 조명 ──────────────────────────────────────────────────
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1);
    dirLight.position.set(5, 10, 7.5);
    scene.add(dirLight);

    const pointLight = new THREE.PointLight(0x7000ff, 2, 10);
    pointLight.position.set(-2, 2, 1);
    scene.add(pointLight);

    const pointLight2 = new THREE.PointLight(0x00f2fe, 2, 10);
    pointLight2.position.set(2, 2, 1);
    scene.add(pointLight2);

    // ── 모델 로딩 ──────────────────────────────────────────────
    const loader = new GLTFLoader();
    loader.load(MODEL_URL, (gltf) => {
        model = gltf.scene;
        scene.add(model);

        // 모델이 그림자를 받도록 설정 및 Bone 매핑
        model.traverse((child) => {
            if (child.isMesh) {
                child.castShadow = true;
                child.receiveShadow = true;
            }
            if (child.isBone) {
                bones[child.name] = child;
            }
        });

        console.info("[ITDA 3D] 모델 로드 완료:", MODEL_URL);
        document.getElementById('joint-status').textContent = "Joints: ACTIVE";
        
        // 초기 포즈 설정 (T-Pose에서 기본 차렷 자세로)
        resetPose();
    });

    window.addEventListener('resize', onWindowResize);
    animate();
}

function resetPose() {
    if (!model) return;
    // 기본 차렷 자세로 살짝 조정
    if (bones['LeftArm']) bones['LeftArm'].rotation.z = Math.PI / 2.5;
    if (bones['RightArm']) bones['RightArm'].rotation.z = -Math.PI / 2.5;
}

function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}

function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
}

// ── 외부 인터페이스 ──────────────────────────────────────────
window.ITDAAvatar = {
    bones,
    updateBone: (name, rotation) => {
        if (bones[name]) {
            // Lerp 적용 (0.1 수준으로 부드럽게)
            bones[name].rotation.x = THREE.MathUtils.lerp(bones[name].rotation.x, rotation.x, 0.2);
            bones[name].rotation.y = THREE.MathUtils.lerp(bones[name].rotation.y, rotation.y, 0.2);
            bones[name].rotation.z = THREE.MathUtils.lerp(bones[name].rotation.z, rotation.z, 0.2);
        }
    }
};

// 시뮬레이션을 위한 임시 로직 (손가락 움직임 확인용)
setInterval(() => {
    if (bones['LeftHandIndex1']) {
        const time = Date.now() * 0.002;
        bones['LeftHandIndex1'].rotation.z = Math.sin(time) * 0.5;
        bones['LeftHandIndex2'].rotation.z = Math.sin(time) * 0.8;
        
        bones['RightHandIndex1'].rotation.z = -Math.sin(time) * 0.5;
        bones['RightHandIndex2'].rotation.z = -Math.sin(time) * 0.8;
    }
}, 16);

init();
