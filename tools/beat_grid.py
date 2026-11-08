#!/usr/bin/env python3
"""Measure a song's tempo, beat grid and bar lines -> beats.json, so cuts land on the bar and loops wrap cleanly.

Usage: python tools/beat_grid.py song.mp3 --out beats.json [--start 30 --end 60] [--bpm-hint 120]

The agent planning the edit cannot hear, so the rhythm is measured, never typed in. Method (numpy + scipy):
  1. Onsets: log-magnitude spectral flux at a 10 ms hop, for the whole spectrum and for the kick band
     (< 150 Hz). Each curve says "something just got louder here".
  2. Tempo: autocorrelation of the onset curve, comb-filtered (a tempo scores by its 1, 2, 3 and 4 beat
     lags together), with a mild preference for 90-140 BPM, or for --bpm-hint, that only settles near-ties
     between half time and double time.
  3. Grid: tempo to 0.01 BPM and the beat phase, by sliding a steady grid over the onsets; then the phase
     is polished to the millisecond on an attack curve (how fast the energy rises, every 1 ms).
  4. Downbeat: which beat of the bar is "1", from the low end (kick and bass level), the kick onset and
     how much the sound changes at each beat. Every bar votes; downbeat_confidence is the winning margin.
  5. Drift: the grid's phase is re-measured in 8 s windows. If it wanders more than 30 ms, the song speeds
     up or slows down somewhere, and one grid will not fit all of it.

Every time in the output is in seconds from the start of the audio file. Beats are a STEADY grid, so they
also fall where a beat is felt but not played. Limits: one tempo and one metre (--beats-per-bar, default 4).
Needs ffmpeg on PATH.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.ndimage import gaussian_filter1d, uniform_filter1d

SR = 22050
HOP = 220                 # 10 ms
NFFT = 1024
FPS = SR / HOP            # onset frames per second
KICK_HZ = 150.0
ATTACK_RATE = 1000        # attack curve: one value per ms


# ---------------------------------------------------------------- signals

def decode(path: Path, start: float, end: float | None) -> np.ndarray:
    """Mono float audio via ffmpeg, so any format works."""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-t", f"{end - start:.3f}"]
    p = subprocess.run(cmd + ["-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    if p.returncode or not p.stdout:
        sys.exit(f"ffmpeg could not decode {path}: {p.stderr.decode()[:300]}")
    return np.frombuffer(p.stdout, np.float32).copy()


def spectrogram(x: np.ndarray):
    """Power spectrogram; frame i is centred on i * HOP / SR."""
    frames = np.lib.stride_tricks.sliding_window_view(np.pad(x, NFFT // 2), NFFT)[::HOP]
    P = np.abs(np.fft.rfft(frames * np.hanning(NFFT), axis=1)) ** 2
    return P, np.fft.rfftfreq(NFFT, 1 / SR)


def onsets(P: np.ndarray, freqs: np.ndarray):
    """Rectified log-magnitude flux, slow trend removed, unit spread: (whole spectrum, kick band)."""
    mag = np.sqrt(P)
    rise = np.maximum(0, np.diff(np.log(mag + 1e-3 * mag.mean() + 1e-12), axis=0))
    curves = []
    for band in (freqs < 11000, (freqs > 20) & (freqs < KICK_HZ)):
        o = np.r_[0, rise[:, band].sum(1)]
        o = np.maximum(0, o - uniform_filter1d(o, int(0.5 * FPS)))
        curves.append(o / (o.std() + 1e-12))
    return curves


def attack_curve(x: np.ndarray) -> np.ndarray:
    """Every 1 ms: how much the energy of the last 5 ms rose against the 5 ms before. Peaks on hits.
    Computed on the full band and above 2 kHz (snare, hats), then summed."""
    total = 0
    hp = signal.sosfiltfilt(signal.butter(2, 2000, "high", fs=SR, output="sos"), x)
    for y in (x, hp):
        cum = np.r_[0, np.cumsum(np.asarray(y, np.float64) ** 2)]
        at = np.round(np.arange(0, len(y) / SR, 1 / ATTACK_RATE) * SR).astype(int)
        h = int(0.005 * SR)
        level = (cum[np.clip(at + h, 0, len(y))] - cum[np.clip(at - h, 0, len(y))]) / (2 * h)
        logl = np.log(level + 1e-3 * cum[-1] / max(len(y), 1) + 1e-12)
        d = np.zeros_like(logl)
        d[5:] = np.maximum(0, logl[5:] - logl[:-5])
        total = total + d / (d.mean() + 1e-12)
    return gaussian_filter1d(total, 1.5)


# ---------------------------------------------------------------- tempo and grid

def comb_score(ac: np.ndarray, bpms: np.ndarray) -> np.ndarray:
    """How strongly the onsets repeat at 1, 2, 3 and 4 beats of each candidate tempo."""
    lag = 60 * FPS / bpms
    lags = np.arange(len(ac))
    return np.mean([np.interp(k * lag, lags, ac, right=0.0) for k in (1, 2, 3, 4)], axis=0)


def preference(bpm, hint):
    """A mild preference, in octaves: one octave away from the preferred tempo costs about 9 %."""
    bpm = np.asarray(bpm, float)
    target = hint if hint else np.clip(bpm, 90, 140)
    return np.exp(-0.5 * (np.log2(bpm / target) / 2.3) ** 2)


def estimate_tempo(o: np.ndarray, lo: float, hi: float, hint: float | None):
    """Best tempo, plus the half-time and double-time alternatives with their scores."""
    oc = o - o.mean()
    ac = signal.correlate(oc, oc, "full", method="fft")[len(oc) - 1:][: len(oc) // 2]
    ac = ac / (len(oc) - np.arange(len(ac)))
    ac = ac / (ac[0] + 1e-12)
    bpms = np.arange(lo, hi + 1e-9, 0.05)
    score = comb_score(ac, bpms)
    peaks, _ = signal.find_peaks(score, distance=20)
    if not len(peaks):
        peaks = [int(np.argmax(score))]
    best = max(peaks, key=lambda i: max(score[i], 0) * preference(bpms[i], hint))
    bpm = float(bpms[best])
    alts = []
    for mult, name in ((0.5, "half time"), (2.0, "double time")):
        fine = np.arange(bpm * mult * 0.98, bpm * mult * 1.02, 0.05)
        s = comb_score(ac, fine)
        j = int(np.argmax(s))
        alts.append({"bpm": round(float(fine[j]), 2), "relation": name, "score": round(float(s[j]), 3)})
    return bpm, round(float(score[best]), 3), alts


def fit_grid(o: np.ndarray, bpm0: float, span=0.006):
    """Slide steady grids over the onsets: tempo within +-0.6 % in 0.01 BPM steps, every phase.
    Returns (bpm, time of a grid beat in seconds)."""
    smooth = gaussian_filter1d(o, 1.0)
    frames = np.arange(len(smooth))
    best = (-1.0, bpm0, 0.0)
    for bpm in np.arange(round(bpm0 * (1 - span), 2), bpm0 * (1 + span), 0.01):
        period = 60 * FPS / bpm
        n = max(int((len(smooth) - 1) / period) - 1, 1)
        phases = np.arange(0, period, 0.25)
        strength = np.interp(phases[:, None] + np.arange(n)[None] * period, frames, smooth).mean(1)
        j = int(np.argmax(strength))
        if strength[j] > best[0]:
            best = (float(strength[j]), float(bpm), float(phases[j]))
    return best[1], (best[2] - 0.5) / FPS          # flux value i is the rise INTO frame i


def comb_peak(D: np.ndarray, times: np.ndarray, reach_ms: int):
    """Shift (ms, sub-ms) that puts `times` on the strongest attacks, how clear that peak is (0..1),
    and how strong."""
    offs = np.arange(-reach_ms, reach_ms + 1)
    idx = np.round(times * ATTACK_RATE).astype(int)[None, :] + offs[:, None]
    v = D[np.clip(idx, 0, len(D) - 1)].mean(1)
    j = int(np.argmax(v))
    frac = 0.0
    if 0 < j < len(v) - 1:                          # parabola through the peak
        a, c, b = v[j - 1], v[j], v[j + 1]
        frac = 0.5 * (a - b) / (a - 2 * c + b + 1e-12)
    clarity = float((v[j] - np.median(v)) / (v[j] + 1e-12))
    return float(offs[j] + frac), clarity, float(v[j])


def polish_phase(D: np.ndarray, bpm: float, t0: float, dur: float) -> float:
    """Move the grid up to 40 ms so its beats sit on the attacks, to the millisecond."""
    period = 60.0 / bpm
    ks = np.arange(int(np.ceil(-(t0 - 0.05) / period)), int((dur - t0 - 0.05) / period) + 1)
    shift_ms, clarity, _ = comb_peak(D, t0 + ks * period, 40)
    return t0 + shift_ms / 1000 if clarity >= 0.25 else t0   # no clear attacks: keep the coarse phase


def measure_drift(D: np.ndarray, bpm: float, first: float, dur: float, win=8.0, hop=2.0):
    """The grid's offset against the local attacks, in 8 s windows. Weak or unclear windows don't count.
    Returns (spread of the offsets in ms, or None if fewer than 2 windows count; windows counted)."""
    period = 60.0 / bpm
    reach = int(min(0.3 * period, 0.15) * 1000)
    rows = []
    for centre in np.arange(0, dur + 1e-9, hop):
        a, b = max(0.0, centre - win / 2), min(dur, centre + win / 2)
        if b - a < win / 2 or (rows and rows[-1][0] == a and rows[-1][1] == b):
            continue
        ks = np.arange(int(np.ceil((a - first) / period)), int(np.floor((b - first) / period)) + 1)
        if len(ks) < 4:
            continue
        shift, clarity, strength = comb_peak(D, first + ks * period, reach)
        rows.append((a, b, shift, clarity, strength))
    if not rows:
        return None, 0
    typical = np.median([r[4] for r in rows])
    good = [r[2] for r in rows if r[3] > 0.6 and r[4] >= 0.4 * typical]
    if len(good) < 2:
        return None, len(good)
    return round(float(max(good) - min(good)), 1), len(good)


# ---------------------------------------------------------------- downbeat

def robust_z(v: np.ndarray, floor: float) -> np.ndarray:
    med = np.median(v)
    spread = max(1.4826 * np.median(np.abs(v - med)), floor, 1e-9)
    return np.clip((v - med) / spread, -3, 3)


def find_downbeat(beats, bpb, frame_t, P, freqs, kick_onset):
    """Score every beat by low-end level + kick onset + how much the sound changes there; the beat
    position (0..bpb-1) with the best average is beat 1. Confidence: each bar votes for its strongest
    position, weighted by how clearly it stands out; confidence is the winner's margin, 0..1."""
    if len(beats) < 2 * bpb:
        return 0, 0.0
    ends = np.r_[beats[1:], beats[-1] + (beats[1] - beats[0])]
    low = P[:, (freqs > 0) & (freqs < KICK_HZ)].sum(1)
    edges = np.geomspace(40, 11000, 25)
    spec = np.stack([P[:, (freqs >= a) & (freqs < b)].sum(1) for a, b in zip(edges[:-1], edges[1:])], 1)
    spec = np.log10(spec + 1e-12)

    def mean_in(v, a, b):
        m = (frame_t >= a) & (frame_t < b)
        return v[m].mean(0) if m.any() else v[np.argmin(np.abs(frame_t - a))]

    low_db = np.array([10 * np.log10(mean_in(low, b, b + min(0.15, (e - b) / 2)) + 1e-12) for b, e in zip(beats, ends)])
    kick = np.array([kick_onset[(frame_t >= b - 0.06) & (frame_t < b + 0.06)].sum() for b in beats])
    vec = np.array([mean_in(spec, b, e) for b, e in zip(beats, ends)])
    change = np.r_[0, np.linalg.norm(np.diff(vec, axis=0), axis=1)]
    change[0] = np.median(change[1:])
    score = robust_z(low_db, 1.0) + robust_z(kick, 0.1 * np.median(kick)) + robust_z(change, 0.1 * np.median(change))

    phase = int(np.argmax([score[p::bpb].mean() for p in range(bpb)]))
    bars = score[: len(score) // bpb * bpb].reshape(-1, bpb)
    ranked = np.sort(bars, 1)
    weight = ranked[:, -1] - ranked[:, -2]            # a bar whose beats all look alike barely votes
    votes = np.bincount(np.argmax(bars, 1), weights=weight, minlength=bpb)
    margin = (votes[phase] - np.delete(votes, phase).max()) / (weight.sum() + 1e-12)
    return phase, float(np.clip(margin, 0, 1))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path, help="the song (any format ffmpeg reads)")
    ap.add_argument("--out", type=Path, default=Path("beats.json"))
    ap.add_argument("--start", type=float, default=0.0, help="window start in seconds (default 0)")
    ap.add_argument("--end", type=float, help="window end in seconds (default: end of file)")
    ap.add_argument("--bpm-hint", type=float, help="roughly the tempo you expect; settles half/double time")
    ap.add_argument("--range", type=float, nargs=2, default=(70.0, 180.0), metavar=("LO", "HI"),
                    help="BPM range to search (default 70 180); narrow it to force half or double time")
    ap.add_argument("--beats-per-bar", type=int, default=4)
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH")
    x = decode(args.audio, args.start, args.end)
    dur = len(x) / SR
    if dur < 4:
        sys.exit(f"window too short to measure a tempo ({dur:.2f} s)")

    P, freqs = spectrogram(x)
    frame_t = np.arange(len(P)) / FPS
    o_all, o_kick = onsets(P, freqs)
    D = attack_curve(x)

    bpm0, evidence, alternatives = estimate_tempo(o_all + o_kick, *args.range, args.bpm_hint)
    bpm, t0 = fit_grid(o_all + 2 * o_kick, bpm0)
    t0 = polish_phase(D, bpm, t0, dur)
    period = 60.0 / bpm
    first = t0 % period
    beats = first + period * np.arange(int((dur - 1e-6 - first) / period) + 1)
    beats = beats[beats < dur]

    bpb = args.beats_per_bar
    phase, confidence = find_downbeat(beats, bpb, frame_t, P, freqs, np.r_[o_kick[1:], 0])
    drift_ms, drift_windows = measure_drift(D, bpm, first, dur)
    downbeats = beats[phase::bpb]

    out = {
        "audio": args.audio.name,
        "window": [round(args.start, 3), round(args.start + dur, 3)],
        "bpm": round(bpm, 2),
        "bpm_alternatives": alternatives,
        "tempo_evidence": evidence,
        "beats_per_bar": bpb,
        "bar_seconds": round(period * bpb, 4),
        "first_downbeat": round(float(downbeats[0] + args.start), 4) if len(downbeats) else None,
        "downbeat_confidence": round(confidence, 2),
        "drift_ms": drift_ms,
        "drift_windows": drift_windows,
        "beats": [round(float(b + args.start), 4) for b in beats],
        "downbeats": [round(float(b + args.start), 4) for b in downbeats],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    alt = ", ".join(f"{a['relation']} {a['bpm']}" for a in alternatives)
    print(f"tempo     {out['bpm']} BPM (alternatives: {alt}), bar = {out['bar_seconds']} s")
    print(f"downbeat  first at {out['first_downbeat']} s, confidence {out['downbeat_confidence']}"
          + ("   <- low: find bar 1 by ear" if confidence < 0.3 else ""))
    if drift_ms is None:
        print(f"drift     not judged ({drift_windows} clear 8 s windows; needs 2 or more)")
    else:
        print(f"drift     {drift_ms} ms across {drift_windows} windows"
              + ("   <- the tempo moves: cut section by section" if drift_ms > 30 else "   (steady)"))
    print(f"beats     {len(beats)}, bars {len(downbeats)}\nwrote {args.out}")


if __name__ == "__main__":
    main()
