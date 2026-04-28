import codecs

path = r'c:\Users\ComHolic\Documents\GitHub\Project_ITDA\frontend\js\motion_loader_v3.js'
with codecs.open(path, 'r', 'utf-8') as f:
    code = f.read()

old_api = """// ── 공개 API ────────────────────────────────────────────────
window.ITDAMotionV3 = {
  load: loadMotion,
  play: playMotion,
  has: hasMotion,
  _cache: CACHE,
};"""

new_api = """// ── 공개 API ────────────────────────────────────────────────
window.ITDAMotionV3 = {
  load: loadMotion,
  play: playMotion,
  has: hasMotion,
  setAsIdle: async function(word) {
    const motion = await loadMotion(word);
    if (!motion || !motion.keyframes?.length) return false;
    if (window.ITDAAvatar5) {
      window.ITDAAvatar5.stopIdle?.();
      _captureHandRest(window.ITDAAvatar5);
      _captureArmRestWorld(window.ITDAAvatar5);
      const kf = motion.keyframes[0];
      const scratch = new Map();
      _applyInterpolated(window.ITDAAvatar5, kf, kf, 1.0, scratch, motion);
      for (const [name, bone] of Object.entries(window.ITDAAvatar5.bones)) {
        if (window.ITDAAvatar5.initialBoneQuats) {
          window.ITDAAvatar5.initialBoneQuats[name] = bone.quaternion.clone();
        }
      }
      console.info(`[MotionV3] Idle pose updated to starting pose of "${word}"`);
    }
  },
  _cache: CACHE,
};"""
code = code.replace(old_api, new_api)

old_end = "window.ITDAMotionV3.browse = browseRange;"
new_end = """window.ITDAMotionV3.browse = browseRange;

// ── 기본 Idle 자세 설정 (감사 시작 자세) ────────────────────
(function _setDefaultIdle() {
  let attempts = 0;
  const timer = setInterval(() => {
    attempts++;
    if (window.ITDAAvatar5?.bones && Object.keys(window.ITDAAvatar5.bones).length > 0) {
      clearInterval(timer);
      const params = new URLSearchParams(location.search);
      // 만약 autoplay 중이 아니라면 기본 Idle 자세를 설정
      if (!params.get('autoplay')) {
        window.ITDAMotionV3.setAsIdle('감사');
      }
    } else if (attempts > 60) {
      clearInterval(timer);
    }
  }, 500);
})();
"""
code = code.replace(old_end, new_end)

old_flip = """        // bone.quaternion = inverse(parentWorld) * W_new
        bone.quaternion.copy(_tmpP).invert().multiply(_tmpW);
      }
      // 자식이 부모 world 를 다시 읽을 때 최신값 보이도록 강제 갱신
      bone.updateMatrixWorld(true);
    }
  }"""

new_flip = """        // bone.quaternion = inverse(parentWorld) * W_new
        bone.quaternion.copy(_tmpP).invert().multiply(_tmpW);
      }
      
      // 손바닥 뒤집힘(반전) 보정: Mixamo 리깅의 손목 로컬 Y축(Roll) 180도 회전
      if (bName === 'RightHand' || bName === 'LeftHand') {
        const flipQuat = scratch.get('handFlip') || scratch.set('handFlip', new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI)).get('handFlip');
        bone.quaternion.multiply(flipQuat);
      }
      
      // 자식이 부모 world 를 다시 읽을 때 최신값 보이도록 강제 갱신
      bone.updateMatrixWorld(true);
    }
  }"""
code = code.replace(old_flip, new_flip)

with codecs.open(path, 'w', 'utf-8') as f:
    f.write(code)
print("Patch applied successfully.")
