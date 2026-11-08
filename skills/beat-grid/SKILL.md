---
name: beat-grid
description: Measure a song's tempo, beat grid and bar lines (downbeats) into beats.json. Use before cutting to the music, looping a section, or animating anything on the beat.
---

# Beat grid

The agent planning the edit cannot hear. So the song's rhythm is measured, never typed in: a tempo
"from the prompt" or "from memory" is wrong often enough to matter (120 asked, 121.4 delivered).

## Run it

```bash
.venv/bin/python tools/beat_grid.py song.mp3 --out remotion/public/beats.json
```

Options: `--start/--end` for an excerpt, `--bpm-hint 90` to settle half time/double time, `--range 70 110`
to force one, `--beats-per-bar 3` for a waltz.

## How it measures (numpy + scipy, no beat-tracking library)

1. **Onsets:** spectral flux (how much the spectrum got louder) every 10 ms, for the whole mix and for the
   kick band below 150 Hz.
2. **Tempo:** autocorrelation of the onsets, scored at 1, 2, 3 and 4 beat lags together (a comb), with a
   mild preference for 90-140 BPM (or your `--bpm-hint`) to settle half/double-time near-ties.
3. **Grid:** a steady grid slid over the onsets gives the tempo to 0.01 BPM and the phase; the phase is then
   polished to the millisecond on the attacks.
4. **Downbeat:** the beat position with the most low end, kick and change in sound; every bar votes.
5. **Drift:** the grid is re-checked in 8 s windows to see whether the song keeps one tempo.

## Read the result

| Field | Meaning |
|---|---|
| `bpm` | The measured tempo, to 0.01 BPM. `bpm_alternatives` shows half and double time with their scores. |
| `beats` | A STEADY grid from the first beat to the end, so it also marks beats that are felt but not played. |
| `first_downbeat`, `downbeats` | Bar lines (beat 1). |
| `downbeat_confidence` | 0..1, the winning margin of the bar votes. Below 0.3, find bar 1 by ear and say so. |
| `drift_ms` | How far the grid wanders against the music across the 8 s windows. Over 30 ms: the tempo moves, so cut section by section. `null`: not enough clear windows to judge (a short excerpt or no drums). |
| `bar_seconds` | One bar. Loops whose length is a whole number of bars wrap cleanly. |

## Use it

- Cut on downbeats, in whole frames: `frame = round(time * fps)`.
- A loop of N bars is `N * bar_seconds` long, starting on a downbeat.
- Words go where they are sung (`lyric-sync`), not on the grid. The grid is for cuts and motion.
- An accent should PEAK on the hit, so start its motion a few frames earlier.
- Downbeats need a kick or bass accent. In a drumless passage, trust your ear over the confidence.
