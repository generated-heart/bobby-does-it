#!/usr/bin/env python3
"""Align KNOWN lyrics to a song: demucs vocal stem -> whisper word timestamps -> LYRICS_TIMING.json.

Usage: python tools/lyric_sync.py song.mp3 lyrics.txt --out LYRICS_TIMING.json [--start 30 --end 60]

This is alignment, not transcription. You give it the lyrics; it finds where each line and word is sung.
  1. demucs (htdemucs, two stems) pulls the vocal out of the mix, so drums and bass stop looking like words.
  2. mlx-whisper transcribes the vocal with word timestamps, prompted with your lyrics.
  3. A fuzzy sequence alignment (Needleman-Wunsch) maps your words onto the heard words, in order.
  4. Whisper's timestamps are smeared by up to a beat, so each line's start/end is snapped to the vocal
     stem's "energy islands" (stretches where the voice is actually sounding). Whisper decides WHICH
     island a line belongs to; the stem decides WHERE it starts and ends.

Lyrics file: one line per row, blank rows ignored. Optional "ID<TAB>text" to name a line.
Every time in the output is in seconds from the start of the audio file.
coverage = share of a line's words that whisper heard. Below 0.6: listen to that line yourself.
Words whisper did not hear are spread evenly between their neighbours and marked "heard": false.

Needs ffmpeg on PATH. mlx-whisper runs on Apple Silicon only; on other machines, swap transcribe() for
openai-whisper or faster-whisper (both give word timestamps).
"""
import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import wave
from pathlib import Path

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
LOW_COVERAGE = 0.6
HEBREW_FINALS = str.maketrans("ךםןףץ", "כמנפצ")


# ---------------------------------------------------------------- audio helpers

def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def cut_window(audio: Path, start: float, end: float, out: Path, rate: int, channels: int):
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(audio),
         "-ac", str(channels), "-ar", str(rate), "-c:a", "pcm_s16le", str(out)])


def separate_vocals(window44: Path, work: Path) -> Path:
    """Run demucs on the window; returns the vocals stem (44.1 kHz stereo wav)."""
    run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-o", str(work / "sep"), str(window44)])
    return work / "sep" / "htdemucs" / window44.stem / "vocals.wav"


def read_wav_mono(path: Path):
    import numpy as np
    with wave.open(str(path)) as w:
        sr, ch = w.getframerate(), w.getnchannels()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768
    return (a.reshape(-1, ch).mean(1) if ch > 1 else a), sr


def envelope(stem: Path, offset: float, hop=0.01, win=0.03):
    """RMS envelope of the vocal stem in dB, one value per `hop` seconds, times in file seconds."""
    import numpy as np
    a, sr = read_wav_mono(stem)
    H, W = int(hop * sr), int(win * sr)
    starts = np.arange(0, max(0, len(a) - W), H)
    db = np.array([20 * np.log10(np.sqrt(np.mean(a[i:i + W] ** 2)) + 1e-9) for i in starts])
    return offset + starts / sr, db


def islands(t, db, thr, min_gap, min_dur):
    """[start, end] stretches where the envelope is above thr; gaps shorter than min_gap are bridged."""
    segs, i = [], 0
    while i < len(db):
        if db[i] > thr:
            j = i
            while j < len(db) and db[j] > thr:
                j += 1
            segs.append([float(t[i]), float(t[j - 1]) + 0.01])
            i = j
        else:
            i += 1
    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < min_gap:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [s for s in merged if s[1] - s[0] >= min_dur]


# ---------------------------------------------------------------- text + alignment

def norm(tok: str) -> str:
    """Lowercase letters and digits only, any script. Drops accents/niqqud, folds Hebrew final letters."""
    tok = "".join(c for c in unicodedata.normalize("NFD", tok.lower()) if not unicodedata.combining(c))
    return re.sub(r"[\W_]", "", tok.translate(HEBREW_FINALS))


def similar(a: str, b: str) -> float:
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()


def align(expected, heard, thresh=0.72, gap=-0.6):
    """Needleman-Wunsch over two token lists with a fuzzy match score.
    Heard words before the first and after the last lyric are free (the window may hold extra singing).
    Returns {expected_index: heard_index} for matched pairs."""
    n, m = len(expected), len(heard)
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    B = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        S[i][0], B[i][0] = S[i - 1][0] + gap, "up"
    for j in range(1, m + 1):
        B[0][j] = "left"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = similar(expected[i - 1], heard[j - 1])
            diag = S[i - 1][j - 1] + (s if s >= thresh else -1.0)
            up, left = S[i - 1][j] + gap, S[i][j - 1] + gap
            best = max(diag, up, left)                 # ties prefer a match, then skipping a lyric word
            S[i][j], B[i][j] = best, "diag" if best == diag else ("up" if best == up else "left")
    i, j = n, max(range(m + 1), key=lambda k: S[n][k])
    pairs = {}
    while i > 0 and j > 0:
        move = B[i][j]
        if move == "diag":
            if similar(expected[i - 1], heard[j - 1]) >= thresh:
                pairs[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif move == "up":
            i -= 1
        else:
            j -= 1
    return pairs


def transcribe(wav16: Path, model: str, prompt: str, language: str):
    """mlx-whisper with word timestamps. The lyrics go in as the prompt so hooks are not hallucinated."""
    import mlx_whisper
    res = mlx_whisper.transcribe(str(wav16), path_or_hf_repo=model, word_timestamps=True, language=language,
                                 initial_prompt=prompt, temperature=0.0, condition_on_previous_text=False,
                                 verbose=None)
    words = []
    for seg in res.get("segments", []):
        for w in seg.get("words", []):
            if norm(w["word"]):
                words.append({"word": w["word"].strip(), "norm": norm(w["word"]),
                              "start": float(w["start"]), "end": float(w["end"])})
    return words, res.get("text", "").strip()


def load_lyrics(path: Path):
    lines = []
    for row in path.read_text(encoding="utf-8").splitlines():
        row = row.strip()
        if not row:
            continue
        lid, text = row.split("\t", 1) if "\t" in row else (f"L{len(lines) + 1:02d}", row)
        lines.append({"id": lid.strip(), "text": text.strip()})
    return lines


# ---------------------------------------------------------------- line timing from the stem

def snap_lines_to_stem(lines, t, db, rise=18.0):
    """Give each line the start/end of the vocal island(s) its whisper span falls in.
    Two lines sung in one breath share an island; they are split at the quiet gap nearest the whisper
    boundary, or flagged when there is no gap."""
    import numpy as np
    sounding = db[db > -100]                       # isolated stems can be digitally silent between phrases
    thr = float(np.percentile(sounding if len(sounding) else db, 10)) + rise
    phrases = islands(t, db, thr, min_gap=0.30, min_dur=0.25)
    gaps_src = islands(t, db, thr, min_gap=0.08, min_dur=0.06)   # syllable-sized islands; their gaps are cut points
    timed = [ln for ln in lines if "start" in ln]
    if not phrases or not timed:
        return thr, phrases
    owner, last = {}, 0
    for ln in timed:
        ws, we = ln["start"], ln["end"]
        overlap = [(max(0.0, min(we, b) - max(ws, a)), k) for k, (a, b) in enumerate(phrases) if k >= last]
        if not overlap:
            continue
        best_overlap, k = max(overlap)
        if best_overlap == 0:                       # no overlap: the nearest island not yet used
            k = min(range(last, len(phrases)), key=lambda q: abs(sum(phrases[q]) / 2 - (ws + we) / 2))
        owner.setdefault(k, []).append(ln)
        last = k
    for k, group in owner.items():
        a, b = phrases[k]
        if len(group) == 1:
            group[0].update(start=round(a, 3), end=round(b, 3), timing="vocal island")
            continue
        gaps = [(gaps_src[i][1], gaps_src[i + 1][0]) for i in range(len(gaps_src) - 1)
                if a < gaps_src[i][1] and gaps_src[i + 1][0] < b]
        bounds = []
        for l1, l2 in zip(group, group[1:]):
            wb = (l1["end"] + l2["start"]) / 2
            near = min(gaps, key=lambda g: abs(sum(g) / 2 - wb)) if gaps else None
            if near and abs(sum(near) / 2 - wb) <= 0.25:
                bounds.append((near[0], near[1], "split at a breath gap"))
            else:
                bounds.append((wb, wb, "CHECK BY EAR: split inside one held phrase at the whisper boundary"))
        starts = [a] + [g[1] for g in bounds]
        ends = [g[0] for g in bounds] + [b]
        notes = [g[2] for g in bounds] + ["vocal island (shared)"]
        for ln, s, e, note in zip(group, starts, ends, notes):
            ln.update(start=round(s, 3), end=round(e, 3), timing=note)
    return thr, phrases


def fill_words(line):
    """Clamp heard words into the line span; spread unheard words evenly between their neighbours."""
    words, s, e = line["words"], line["start"], line["end"]
    for w in words:
        if w["heard"]:
            w["start"] = min(max(w["start"], s), e)
            w["end"] = min(max(w["end"], w["start"]), e)
    i = 0
    while i < len(words):
        if words[i]["heard"]:
            i += 1
            continue
        j = i
        while j < len(words) and not words[j]["heard"]:
            j += 1
        left = words[i - 1]["end"] if i > 0 else s
        right = words[j]["start"] if j < len(words) else e
        step = max(0.0, right - left) / (j - i)
        for q in range(i, j):
            words[q]["start"] = round(left + step * (q - i), 3)
            words[q]["end"] = round(left + step * (q - i + 1), 3)
        i = j


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path, help="the song (any format ffmpeg reads)")
    ap.add_argument("lyrics", type=Path, help="the KNOWN lyrics, one line per row")
    ap.add_argument("--out", type=Path, default=Path("LYRICS_TIMING.json"))
    ap.add_argument("--start", type=float, default=0.0, help="window start in seconds (default 0)")
    ap.add_argument("--end", type=float, help="window end in seconds (default: end of file)")
    ap.add_argument("--language", default="en", help="whisper language code, e.g. en, es, he")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"mlx-whisper model (default {DEFAULT_MODEL})")
    ap.add_argument("--no-separate", action="store_true", help="skip demucs and use the mix (worse on music)")
    ap.add_argument("--stem", type=Path, help="reuse a vocal stem saved earlier for the SAME window (skips demucs)")
    ap.add_argument("--keep-stem", type=Path, help="save the demucs vocal stem here, to reuse with --stem")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found on PATH")
    lines = load_lyrics(args.lyrics)
    if not lines:
        sys.exit("the lyrics file is empty")
    end = args.end if args.end is not None else duration(args.audio)
    work = Path(tempfile.mkdtemp(prefix="lyric_sync_"))

    stem = None
    if args.stem:
        stem = args.stem
    elif not args.no_separate:
        print("demucs: separating the vocal ...", file=sys.stderr)
        window44 = work / "window.wav"
        cut_window(args.audio, args.start, end, window44, 44100, 2)
        stem = separate_vocals(window44, work)
        if args.keep_stem:
            args.keep_stem.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(stem, args.keep_stem)
    wav16 = work / "whisper16.wav"
    if stem:
        run(["ffmpeg", "-v", "error", "-y", "-i", str(stem), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav16)])
    else:
        cut_window(args.audio, args.start, end, wav16, 16000, 1)

    print("whisper: word timestamps ...", file=sys.stderr)
    heard, transcript = transcribe(wav16, args.model, " ".join(ln["text"] for ln in lines), args.language)
    for w in heard:
        w["start"] += args.start
        w["end"] += args.start

    expected = [(li, tok, norm(tok)) for li, ln in enumerate(lines) for tok in ln["text"].split() if norm(tok)]
    pairs = align([e[2] for e in expected], [w["norm"] for w in heard])
    for li, ln in enumerate(lines):
        idx = [k for k, e in enumerate(expected) if e[0] == li]
        ln["words"] = []
        for k in idx:
            h = heard[pairs[k]] if k in pairs else None
            ln["words"].append({"text": expected[k][1], "heard": h is not None,
                                "start": round(h["start"], 3) if h else None, "end": round(h["end"], 3) if h else None})
        matched = [w for w in ln["words"] if w["heard"]]
        ln["coverage"] = round(len(matched) / max(1, len(idx)), 2)
        if matched:
            ln["start"], ln["end"] = min(w["start"] for w in matched), max(w["end"] for w in matched)
            ln["timing"] = "whisper words"

    if stem:
        t, db = envelope(stem, args.start)
        snap_lines_to_stem(lines, t, db)
    for ln in lines:
        if "start" in ln:
            fill_words(ln)

    out = {
        "audio": args.audio.name,
        "window": [round(args.start, 3), round(end, 3)],
        "method": ("vocal stem + " if stem else "") + f"whisper word timestamps ({args.model}), "
                  "aligned to the given lyrics",
        "note": "Seconds from the start of the audio file. coverage < 0.6 or a CHECK BY EAR note: listen. "
                "Lines with no start were not heard at all; time them by ear or drop them.",
        "lines": [{"id": ln["id"], "text": ln["text"], "start": ln.get("start"), "end": ln.get("end"),
                   "coverage": ln["coverage"], "timing": ln.get("timing", "not heard"), "words": ln["words"]}
                  for ln in lines],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nheard: {transcript}\n")
    print(f"{'id':6} {'cov':>4} {'start':>7} {'end':>7}  text")
    for ln in out["lines"]:
        flag = ""
        if ln["coverage"] < LOW_COVERAGE:
            flag = "   <- low coverage, listen"
        elif ln["timing"].startswith("CHECK"):
            flag = "   <- " + ln["timing"]
        s = f"{ln['start']:7.2f}" if ln["start"] is not None else "      -"
        e = f"{ln['end']:7.2f}" if ln["end"] is not None else "      -"
        print(f"{ln['id']:6} {ln['coverage']:>4} {s} {e}  {ln['text']}{flag}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
