"""
audio_analyzer.py - 9단계: 오디오 사운드 분석 모듈
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3대 약속 #2: /api/ 폴더 안에서만 작업

단순 음성 인식(STT)을 넘어 소리의 특성을 분석합니다.
  · 소리 유형 분류: 음성 / 음악 / 소음 / 침묵
  · 에너지 레벨 (실시간 볼륨 강도)
  · 주파수 대역 분포 (저음 / 중음 / 고음)
  · 감정 힌트 (차분 / 활기 / 긴장 / 중립)

STT 라우터에서 동일한 오디오 파일로 Whisper 와 함께 호출됩니다.
"""

import logging
from typing import Optional

logger = logging.getLogger("itda.audio_analyzer")

# ── librosa 지연 임포트 (선택적 의존성) ─────────────────────
def _import_librosa():
    try:
        import librosa
        import numpy as np
        return librosa, np
    except ImportError:
        return None, None


# ── 사운드 타입 분류 임계값 ──────────────────────────────────
_THRESHOLDS = {
    "silence_rms":        0.008,   # 이하 → 침묵
    "speech_zcr_min":     0.04,    # 음성: ZCR 범위
    "speech_zcr_max":     0.25,
    "speech_centroid_min": 300,    # Hz — 음성 주파수 범위
    "speech_centroid_max": 4000,
    "music_zcr_max":      0.08,    # 음악: 낮은 ZCR (조화로운 소리)
    "music_energy_min":   0.03,
}

# 감정 매핑 (sound_type + energy → 감정 힌트)
_EMOTION_MAP = {
    ("silence", "low"):   "중립",
    ("speech",  "low"):   "차분",
    ("speech",  "mid"):   "활기",
    ("speech",  "high"):  "긴장",
    ("music",   "low"):   "차분",
    ("music",   "mid"):   "활기",
    ("music",   "high"):  "활기",
    ("noise",   "low"):   "중립",
    ("noise",   "mid"):   "긴장",
    ("noise",   "high"):  "긴장",
}


def analyze_audio(audio_path: str) -> dict:
    """
    오디오 파일을 분석하여 특성 딕셔너리를 반환합니다.

    Returns:
        {
          sound_type:         'speech' | 'music' | 'noise' | 'silence'
          energy_rms:         0.0 ~ 1.0   (정규화된 에너지)
          energy_level:       'low' | 'mid' | 'high'
          spectral_centroid:  Hz (소리의 '밝기')
          zcr:                Zero Crossing Rate
          dominant_band:      'bass' | 'mid' | 'high'
          band_energies:      { bass, mid, high }  각 0.0~1.0
          emotion_hint:       '차분' | '활기' | '긴장' | '중립'
        }
    """
    librosa, np = _import_librosa()

    if librosa is None:
        logger.warning("[AudioAnalyzer] librosa 미설치 → 기본값 반환")
        return _default_analysis()

    try:
        # ── 오디오 로드 (16kHz 모노) ──────────────────────────
        y, sr = librosa.load(audio_path, sr=16000, mono=True)

        if len(y) == 0:
            return _default_analysis()

        # ── 1. RMS 에너지 ─────────────────────────────────────
        rms_raw = float(np.sqrt(np.mean(y ** 2)))
        rms_norm = min(rms_raw * 12.0, 1.0)   # 0~1 정규화

        # ── 2. ZCR ───────────────────────────────────────────
        zcr = float(np.mean(librosa.feature.zero_crossing_rate(y)))

        # ── 3. 스펙트럼 중심 주파수 ───────────────────────────
        spec_centroid = float(
            np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))
        )

        # ── 4. 주파수 대역별 에너지 ───────────────────────────
        # STFT → 주파수 빈 → 대역 분리
        S = np.abs(librosa.stft(y, n_fft=512))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=512)

        def _band_energy(f_lo, f_hi):
            mask = (freqs >= f_lo) & (freqs < f_hi)
            return float(np.mean(S[mask]) ** 2) if mask.any() else 0.0

        bass_e  = _band_energy(20,   300)
        mid_e   = _band_energy(300,  4000)
        high_e  = _band_energy(4000, 8000)

        total_e = bass_e + mid_e + high_e + 1e-9
        band_energies = {
            "bass": round(bass_e / total_e, 3),
            "mid":  round(mid_e  / total_e, 3),
            "high": round(high_e / total_e, 3),
        }
        dominant_band = max(band_energies, key=band_energies.get)

        # ── 5. 소리 유형 분류 (규칙 기반) ─────────────────────
        sound_type = _classify(rms_raw, zcr, spec_centroid)

        # ── 6. 에너지 레벨 ────────────────────────────────────
        energy_level = (
            "low"  if rms_norm < 0.25 else
            "mid"  if rms_norm < 0.65 else
            "high"
        )

        # ── 7. 감정 힌트 ──────────────────────────────────────
        emotion_hint = _EMOTION_MAP.get((sound_type, energy_level), "중립")

        result = {
            "sound_type":        sound_type,
            "energy_rms":        round(rms_norm, 4),
            "energy_level":      energy_level,
            "spectral_centroid": round(spec_centroid, 1),
            "zcr":               round(zcr, 5),
            "dominant_band":     dominant_band,
            "band_energies":     band_energies,
            "emotion_hint":      emotion_hint,
        }
        logger.debug(f"[AudioAnalyzer] {result}")
        return result

    except Exception as e:
        logger.error(f"[AudioAnalyzer] 분석 오류: {e}", exc_info=True)
        return _default_analysis()


# ── 소리 유형 분류 (헤이리스틱) ─────────────────────────────
def _classify(rms: float, zcr: float, centroid: float) -> str:
    t = _THRESHOLDS
    if rms < t["silence_rms"]:
        return "silence"
    if (t["speech_zcr_min"] <= zcr <= t["speech_zcr_max"] and
            t["speech_centroid_min"] <= centroid <= t["speech_centroid_max"]):
        return "speech"
    if (zcr <= t["music_zcr_max"] and rms >= t["music_energy_min"]):
        return "music"
    return "noise"


def _default_analysis() -> dict:
    return {
        "sound_type":        "silence",
        "energy_rms":        0.0,
        "energy_level":      "low",
        "spectral_centroid": 0.0,
        "zcr":               0.0,
        "dominant_band":     "mid",
        "band_energies":     {"bass": 0.33, "mid": 0.34, "high": 0.33},
        "emotion_hint":      "중립",
    }
