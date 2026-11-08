// A lyric video made entirely in code.
//
//   public/LYRICS_TIMING.json  (tools/lyric_sync.py)  -> each word appears on its measured sung time
//   public/beats.json          (tools/beat_grid.py)   -> the 3D shape kicks on every beat, harder on bar 1
//   public/<audio>             (optional)             -> the song, named in LYRICS_TIMING.json "audio"
//
// Everything is a function of the current time t. Nothing animates from a typed-in timestamp.

import React, {useMemo} from 'react';
import {AbsoluteFill, CalculateMetadataFunction, Html5Audio, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {PALETTE, printMaterial} from './print';

// ---- data ------------------------------------------------------------------------------------------

export type Word = {text: string; start: number; end: number; heard?: boolean};
export type Line = {id: string; text: string; start: number | null; end: number | null; words: Word[]};
export type Timing = {audio?: string; window?: [number, number]; lines: Line[]};
export type Beats = {bpm: number; beats: number[]; downbeats: number[]};
export type LyricVideoProps = {timing: Timing; beats: Beats; audio: string | null};

export const FPS = 30;
const EMPTY: LyricVideoProps = {timing: {lines: []}, beats: {bpm: 120, beats: [], downbeats: []}, audio: null};
export const defaultProps = EMPTY;

const loadJson = async <T,>(file: string, fallback: T): Promise<T> => {
  try {
    const r = await fetch(staticFile(file));
    return r.ok ? ((await r.json()) as T) : fallback;
  } catch {
    return fallback;
  }
};

const exists = async (file: string) => {
  try {
    return (await fetch(staticFile(file), {method: 'HEAD'})).ok;
  } catch {
    return false;
  }
};

/** Reads the JSON files from public/ and sizes the video to the lyric window. */
export const calculateMetadata: CalculateMetadataFunction<LyricVideoProps> = async ({props}) => {
  const timing = await loadJson<Timing>('LYRICS_TIMING.json', EMPTY.timing);
  const beats = await loadJson<Beats>('beats.json', EMPTY.beats);
  const audio = timing.audio && (await exists(timing.audio)) ? timing.audio : null;
  const from = timing.window?.[0] ?? 0;
  const lastEnd = Math.max(0, ...timing.lines.map((l) => (l.end ?? 0) + 1.5));
  const to = Math.max(timing.window?.[1] ?? 0, lastEnd, from + 2);
  return {
    durationInFrames: Math.ceil((to - from) * FPS),
    fps: FPS,
    width: 1080,
    height: 1920,
    props: {...props, timing, beats, audio},
  };
};

// ---- timing helpers --------------------------------------------------------------------------------

/** The latest time in `times` at or before t, or -Infinity. */
const lastAtOrBefore = (times: number[], t: number) => {
  let best = -Infinity;
  for (const x of times) if (x <= t) best = x;
  return best;
};

/** A decaying kick: 1 at time `at`, then falling off. 0 before `at`. */
const kick = (t: number, at: number, decay: number) => (t >= at ? Math.exp(-(t - at) * decay) : 0);

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const easeOutBack = (x: number) => 1 + 2.2 * Math.pow(x - 1, 3) + 1.2 * Math.pow(x - 1, 2);

// Words start forming slightly BEFORE their sung time, so they are readable ON the syllable, not after it.
const LEAD = 0.12;
const ENTER = 0.16;
// Lines stay a little after the voice stops, so a held last note is not cut off.
const HOLD = 0.4;
const EXIT = 0.2;

// ---- the 3D scene ----------------------------------------------------------------------------------

const Scene: React.FC<{t: number; beat: number; bar: number}> = ({t, beat, bar}) => {
  const knot = useMemo(() => printMaterial({base: PALETTE.red, cell: 11}), []);
  const backdrop = useMemo(() => printMaterial({base: PALETTE.paper, shade: false, dark: 0.08, cell: 14}), []);
  // Uniforms are plain objects: set them every frame from t. Remotion renders each frame from scratch.
  for (const m of [knot, backdrop]) m.uniforms.uTime.value = t;
  knot.uniforms.uCell.value = 11 + 5 * bar;                 // the dot screen coarsens on each downbeat
  const scale = 0.7 * (1 + 0.12 * beat + 0.18 * bar);
  return (
    <>
      <mesh position={[0, 0, -4]} material={backdrop}>
        <planeGeometry args={[12, 20]} />
      </mesh>
      <mesh position={[0, 1.1, 0]} rotation={[t * 0.35, t * 0.5 + bar * 0.6, 0]} scale={scale} material={knot}>
        <torusKnotGeometry args={[0.8, 0.28, 220, 32]} />
      </mesh>
    </>
  );
};

// ---- the type --------------------------------------------------------------------------------------

const LyricLine: React.FC<{t: number; line: Line}> = ({t, line}) => {
  const end = line.end ?? 0;
  const leaving = clamp01((t - (end + HOLD)) / EXIT);
  return (
    <div
      style={{
        position: 'absolute', left: 90, right: 90, top: 1180,
        display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: '0 26px',
        opacity: 1 - leaving, transform: `translateY(${-40 * leaving}px) scale(${1 + 0.08 * leaving})`,
      }}
    >
      {line.words.map((w, i) => {
        const k = clamp01((t - (w.start - LEAD)) / ENTER);
        const singing = t >= w.start && t < w.end;
        return (
          <span
            key={i}
            style={{
              display: 'inline-block',
              fontFamily: '"Futura", "Avenir Next Condensed", Impact, "Arial Black", sans-serif',
              fontWeight: 800, fontSize: 104, lineHeight: 1.1, textTransform: 'uppercase',
              color: singing ? PALETTE.paper : PALETTE.ink,
              WebkitTextStroke: `8px ${PALETTE.ink}`, paintOrder: 'stroke fill',
              textShadow: `7px 6px 0 ${singing ? PALETTE.red : PALETTE.blue}`,  // the second "plate", out of register
              opacity: k > 0 ? 1 : 0,
              transform: `scale(${k > 0 ? easeOutBack(k) : 0})`,
            }}
          >
            {w.text}
          </span>
        );
      })}
    </div>
  );
};

// ---- the composition -------------------------------------------------------------------------------

export const LyricVideo: React.FC<LyricVideoProps> = ({timing, beats, audio}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const from = timing.window?.[0] ?? 0;
  const t = from + frame / fps;                                // time in the SONG, in seconds

  const beat = kick(t, lastAtOrBefore(beats.beats, t), 7);
  const bar = kick(t, lastAtOrBefore(beats.downbeats, t), 4);
  // the latest line that has started; it stays until its hold and exit are over
  const started = timing.lines.filter((l) => l.start !== null && l.end !== null && t >= l.start - LEAD);
  const latest = started[started.length - 1];
  const line = latest && t < (latest.end ?? 0) + HOLD + EXIT ? latest : undefined;

  return (
    <AbsoluteFill style={{backgroundColor: PALETTE.paper}}>
      {audio ? <Html5Audio src={staticFile(audio)} trimBefore={Math.round(from * fps)} /> : null}
      <ThreeCanvas width={width} height={height} linear flat camera={{position: [0, 0, 7], fov: 35}}>
        <Scene t={t} beat={beat} bar={bar} />
      </ThreeCanvas>
      {line ? <LyricLine key={line.id} t={t} line={line} /> : null}
      {timing.lines.length === 0 ? (
        <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontSize: 48, color: PALETTE.ink}}>
          Put LYRICS_TIMING.json and beats.json in remotion/public/
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};
