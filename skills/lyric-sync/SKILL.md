---
name: lyric-sync
description: Find where each lyric line and word is actually sung in a song, and write LYRICS_TIMING.json. Use before any caption, kinetic type or cut placed "on a word".
---

# Lyric sync

Captions that are a little late feel like a dubbed film. Do not type timestamps by ear or read them off a
waveform of the full mix: a drum hit and a sung syllable look the same there. Measure.

## Run it

```bash
.venv/bin/python tools/lyric_sync.py song.mp3 lyrics.txt --out remotion/public/LYRICS_TIMING.json
```

- `lyrics.txt` is the KNOWN lyric, one line per row. The tool aligns; it never invents words.
- `--start/--end` limit it to an excerpt. Times in the output are still seconds in the full file.
- demucs runs by default. Save the stem once with `--keep-stem vocals.wav`, then reuse it with `--stem vocals.wav`.
- If the song comes with its own isolated lead vocal, pass that as `--stem`; it beats demucs when there are
  backing vocals.
- Other languages: `--language es`, `--language he`, ...

## How it works, so you can read the result

1. demucs separates the vocal, so the drums stop looking like words.
2. Whisper transcribes the vocal with word timestamps, prompted with the lyrics (without a prompt it
   hallucinates on repetitive hooks).
3. Your words are aligned to the heard words in order (fuzzy matching, so "you're" = "youre").
4. Whisper's word times are smeared by up to a beat. So a line's start and end come from the vocal stem's
   energy islands (where the voice actually sounds); whisper only decides which island is which line.

## Read the result

- `coverage` below 0.6: the line is unverified. Listen to it, or ask the human about that line only.
- `timing` saying `CHECK BY EAR`: two lines were sung in one breath and the split is a guess.
- `heard: false` words were placed evenly between their neighbours, not measured.
- A wordless passage (humming, "ooh") is still voice on the stem. If a caption lands on one, check it.
- The human's ear is the final authority. Whisper is evidence. If they disagree, re-run and listen; never average.

## Rules

- One timing file per excerpt. Everything that renders words reads it; nothing keeps a second copy of the text.
- Delete a caption rather than keep one nobody can hear.
