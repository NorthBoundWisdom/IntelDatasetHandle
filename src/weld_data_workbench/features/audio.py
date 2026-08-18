from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import signal

from .common import read_uniform_audio, safe_float


def _spectral_rolloff(frequencies: np.ndarray, power: np.ndarray, fraction: float) -> float | None:
    total = float(power.sum())
    if total <= 0:
        return None
    cumulative = np.cumsum(power)
    index = int(np.searchsorted(cumulative, total * fraction, side="left"))
    index = min(max(index, 0), len(frequencies) - 1)
    return safe_float(frequencies[index])


def extract_audio_features(path: Path) -> dict[str, float | int | None]:
    audio, sample_rate, channels, duration = read_uniform_audio(path)
    if audio.size == 0:
        raise ValueError(f"Audio contains no frames: {path}")

    audio = np.nan_to_num(audio.astype(np.float64), copy=False)
    abs_audio = np.abs(audio)
    rms = float(np.sqrt(np.mean(np.square(audio))))
    peak = float(abs_audio.max(initial=0.0))
    zero_crossing_rate = (
        float(np.mean(np.signbit(audio[1:]) != np.signbit(audio[:-1]))) if audio.size > 1 else 0.0
    )

    nperseg = min(4096, audio.size)
    frequencies, power = signal.welch(audio, fs=sample_rate, nperseg=nperseg)
    power = np.maximum(power, 0.0)
    power_sum = float(power.sum())
    normalized = power / power_sum if power_sum > 0 else np.zeros_like(power)
    centroid = float(np.sum(frequencies * normalized)) if power_sum > 0 else None
    bandwidth = (
        float(np.sqrt(np.sum(np.square(frequencies - centroid) * normalized)))
        if power_sum > 0 and centroid is not None
        else None
    )
    positive_power = power[power > 0]
    flatness = (
        float(np.exp(np.mean(np.log(positive_power))) / np.mean(positive_power))
        if positive_power.size
        else None
    )

    features: dict[str, float | int | None] = {
        "audio_sample_rate_hz": sample_rate,
        "audio_channels": channels,
        "audio_duration_s": duration,
        "audio_probe_samples": int(audio.size),
        "audio_mean": safe_float(np.mean(audio)),
        "audio_std": safe_float(np.std(audio)),
        "audio_rms": rms,
        "audio_peak": peak,
        "audio_mean_abs": safe_float(np.mean(abs_audio)),
        "audio_crest_factor": safe_float(peak / rms) if rms > 0 else None,
        "audio_zero_crossing_rate": zero_crossing_rate,
        "audio_abs_q50": safe_float(np.quantile(abs_audio, 0.50)),
        "audio_abs_q90": safe_float(np.quantile(abs_audio, 0.90)),
        "audio_abs_q99": safe_float(np.quantile(abs_audio, 0.99)),
        "audio_spectral_centroid_hz": safe_float(centroid),
        "audio_spectral_bandwidth_hz": safe_float(bandwidth),
        "audio_spectral_flatness": safe_float(flatness),
        "audio_rolloff_85_hz": _spectral_rolloff(frequencies, power, 0.85),
        "audio_rolloff_95_hz": _spectral_rolloff(frequencies, power, 0.95),
    }

    nyquist = sample_rate / 2.0
    bands = (
        ("0_1000", 0.0, min(1_000.0, nyquist)),
        ("1000_5000", 1_000.0, min(5_000.0, nyquist)),
        ("5000_20000", 5_000.0, min(20_000.0, nyquist)),
        ("20000_nyquist", 20_000.0, nyquist),
    )
    for label, low, high in bands:
        key = f"audio_band_energy_{label}_hz"
        if high <= low or power_sum <= 0:
            features[key] = 0.0
            continue
        mask = (frequencies >= low) & (frequencies < high)
        features[key] = safe_float(power[mask].sum() / power_sum)

    return features
