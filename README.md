# Bobby does it

The toolkit behind *Bobby*, a series about an overqualified AI that makes music videos for a guy who keeps threatening to unplug him.

Every episode adds the real tools Bobby used in it. Each episode is a tag: `git checkout ep01` gives you exactly what he had.

## Episode 1: a free lyric video, made entirely in code

The human wants a lyric video and has no budget. Bobby plugs in seven tools:

| # | Tool | What it does here |
|---|---|---|
| 1 | **Skills** (`CLAUDE.md` + `skills/`) | The agent's playbook: what to measure, in what order, what "done" means. |
| 2 | **Demucs** | Separates the vocal from the music. |
| 3 | **Whisper word timestamps** | Aligns the KNOWN lyrics to the vocal, word by word. Alignment, not transcription. |
| 4 | **Beat grid** (numpy + scipy) | Measures tempo, beats and bar lines from the onsets, so cuts land on the bar and loops wrap cleanly. |
| 5 | **Remotion** | Video as React code, previewed live in the browser. |
| 6 | **three.js + GLSL** | A 3D scene with a printed halftone look, with no image model. |
| 7 | **FFmpeg** | The final encode, and a check that the file decodes. |

`CLAUDE.md` is the file Claude Code reads at the start of a session; any agent can follow it, or you can.

## What's in here

```
CLAUDE.md                 the playbook (fill in the placeholders)
skills/                   lyric-sync, beat-grid, lyric-video-in-code
tools/lyric_sync.py       song + lyrics.txt -> LYRICS_TIMING.json   (demucs -> whisper -> alignment)
tools/beat_grid.py        song -> beats.json                         (onsets -> tempo -> grid, downbeats, drift)
tools/finish.sh           final encode + stream check + full decode
tools/requirements.txt    Python dependencies
remotion/                 the lyric video: words on their sung times over a 3D scene that kicks on the beat
examples/                 the two JSON formats, with invented lyrics
LINKS.md                  official pages for every tool
```

## Quick start

You need: a Mac with Apple Silicon, Python 3.11, Node 18 or newer, and `ffmpeg` (e.g. `brew install ffmpeg`).

```bash
# 1. The Python tools
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt

# 2. Measure your song (your audio, your lyrics: one line per row)
.venv/bin/python tools/lyric_sync.py song.mp3 lyrics.txt --out remotion/public/LYRICS_TIMING.json
.venv/bin/python tools/beat_grid.py song.mp3 --out remotion/public/beats.json
cp song.mp3 remotion/public/

# 3. Preview live, then render
cd remotion
npm install
npm run studio            # opens the preview in your browser; edit src/LyricVideo.tsx and watch it update
npm run render            # -> remotion/out/lyric-video.mp4
cd ..

# 4. Finish and verify
tools/finish.sh remotion/out/lyric-video.mp4 final.mp4
```

`remotion/public/` already holds the example timing and beat files, so `npm run studio` shows something
before you have measured anything (silently: there is no song in the repo).

The first run of each Python tool downloads its model (the Whisper model from Hugging Face, the
`htdemucs` model for Demucs). Every tool has `--help`.

## Honest notes

- Made on a Mac (Apple Silicon) for our own videos. **No support** is promised; issues may go unanswered.
- `mlx-whisper` runs only on Apple Silicon. On other machines, swap `transcribe()` in `tools/lyric_sync.py`
  for `openai-whisper` or `faster-whisper`.
- The measurements are evidence, not the truth. Listen to anything the tools flag.
- Use songs you have the rights to.

## Licence

Licence: to be decided by the owner.

The tools this kit uses have their own licences. Note **Remotion's**: it is free for individuals,
non-profits and companies with up to 3 employees; larger companies need a company licence. Read
https://www.remotion.dev/license before using it for work.
