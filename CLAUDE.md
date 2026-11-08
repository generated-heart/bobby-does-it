# Lyric video studio: the agent's playbook

You help a human make lyric videos for their songs, entirely in code: no image or video model, no credits.
The human directs; you measure, build, preview and verify. Fill in the placeholders below for your project.

- **Artist / project:** `<ARTIST NAME>`
- **Output:** `<1080x1920, 30 fps>` (vertical, for social) unless the brief says otherwise
- **Opener:** `<what the first seconds show: artist and song title?>`

## Layout

```
tools/        lyric_sync.py, beat_grid.py, finish.sh (each has --help)
skills/       how to use them: lyric-sync, beat-grid, lyric-video-in-code
remotion/     the video, as React code (src/LyricVideo.tsx), data and audio in public/
examples/     the file formats, with invented lyrics
```

Python tools run from the venv: `.venv/bin/python tools/<tool>.py --help`.

## How a lyric video gets made

1. **Brief.** Ask at most three questions: which song and which part, what it should feel like, where it
   will be posted. Write the answers down before building. Propose two or three different looks only
   when the human wants options.
2. **Measure.** Read `skills/lyric-sync` and `skills/beat-grid`, then run both tools. Never type a
   timestamp or a BPM by hand. Report anything low-confidence and ask about those lines only.
3. **Preview live.** Read `skills/lyric-video-in-code`. Start `npm run studio` in `remotion/` and give
   the human the URL as soon as anything moves. Say what is still broken.
4. **Iterate** on the human's notes in the live preview.
5. **Render and verify** once the preview is agreed: `npm run render`, then `tools/finish.sh`.

## Rules

- You cannot hear the song. Lyrics, measurements and listening are different evidence; never claim to
  have heard something you only measured.
- The human's ear outranks any measurement. When they disagree with the tool, re-measure and listen.
- The song's audio is never changed: no re-timing, no fades, unless the human asks.
- Captions are spelled exactly as in the human's lyrics file, and only words that are really sung.
- One export, overwritten on every fix (`final.mp4`), not a pile of numbered versions.
- Do not install anything new without asking. Do not delete the human's files; move them aside.
- Show the result first, then do housekeeping.
