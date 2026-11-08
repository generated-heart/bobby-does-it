---
name: lyric-video-in-code
description: Build a lyric video entirely in code with Remotion (React) and three.js shaders, from LYRICS_TIMING.json and beats.json; preview it live, then render and verify the file. Use when the brief is a free lyric video with no image or video model.
---

# A lyric video in code

No image model, no video model, no credits. Type, a 3D scene and a shader are the whole picture.

## The order

1. Measure first: `lyric-sync` -> `LYRICS_TIMING.json`, `beat-grid` -> `beats.json`. Copy both, and the
   song, into `remotion/public/`. The `audio` field of the timing file names the song file.
2. Preview live: `cd remotion && npm run studio`. Give the human the URL now, even while things are
   still rough, and say what is still broken. A note in the preview costs seconds; a note on a render
   costs a render.
3. Change the look in `src/LyricVideo.tsx` (type, scene) and `src/print.ts` (the shader). The preview
   hot-reloads.
4. Render only when the preview is agreed: `npm run render`.
5. Finish and verify: `tools/finish.sh remotion/out/lyric-video.mp4 final.mp4`.

## Rules that make it feel in sync

- Everything is a function of time `t`. Never hand-write frame numbers; convert seconds to frames once.
- **Lead:** start a word's entrance ~0.1 s before its sung time, so it is readable ON the syllable.
  A word that starts appearing on its onset reads late, even when the timestamp is right.
- **Hold:** keep a line up a little after the voice stops, then let it leave with a move. A line that
  vanishes exactly at its end cuts off a held note.
- **Beat:** motion kicks on beats and harder on downbeats, and decays between them. Repeated hits should
  build, not repeat at the same size.
- Text stays inside a safe area: social apps put buttons along the right edge and captions at the bottom.
- Check readability at phone size. If the background fights the type, simplify the background.

## The print look (three.js + GLSL)

`src/print.ts` shades every surface with a screen-space halftone: darkness from a simple light becomes
dot size, on paper with grain that re-seeds 12 times a second (a stop-motion "boil"). The canvas uses
`linear flat`, so the hex colours you write are the colours you get. One shader on every surface is what
makes different objects look like one printed thing.

## Verify before calling it done

- `npx tsc --noEmit` and `npx remotion compositions src/index.ts` in `remotion/`.
- Watch the render at full speed. Stills are for checking layout, not timing.
- `tools/finish.sh`: both streams present, the expected frame count, and a full decode with no errors.
