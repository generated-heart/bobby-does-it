#!/usr/bin/env bash
# Usage: tools/finish.sh remotion/out/lyric-video.mp4 final.mp4
#
# The final encode, then proof that the file is good:
#   1. Re-encode to a plain H.264 + AAC MP4 that every phone and app plays. Remotion's render is
#      full-range video (yuvj420p); some players stall on that, so it is converted to standard
#      limited-range BT.709 in the filter chain (a -pix_fmt flag alone does not convert it).
#   2. Print both streams (codec, size, frame count, duration).
#   3. Decode every frame. Any error means the file is broken, whatever the player shows.
set -euo pipefail

usage() { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; }
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 0; fi
if [[ $# -ne 2 ]]; then usage; exit 1; fi
in="$1"; out="$2"

ffmpeg -v error -y -i "$in" \
  -vf "scale=out_range=tv:out_color_matrix=bt709,format=yuv420p" \
  -c:v libx264 -preset slow -crf 20 -profile:v high \
  -color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709 \
  -c:a aac -b:a 192k -movflags +faststart "$out"

ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,nb_frames,duration,pix_fmt \
  -of compact "$out"
ffmpeg -v error -i "$out" -f null - && echo "decodes cleanly: $out"
