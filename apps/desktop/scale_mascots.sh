#!/bin/bash
# MAYA's mascot GIFs are 1600x960. Decoding them at that size and scaling every frame down
# to the ~230px she's drawn at costs more than a whole CPU core on the Pi, which makes touch
# input lag while she's on screen. This writes 480px-wide copies next to them (~15% of a
# core instead). The app uses them when they exist and falls back to the originals when they
# don't, so this is safe to skip — it just runs slower.
set -e
cd "$(dirname "$0")/assets/maya"
mkdir -p scaled
for gif in idle listen think talking; do
    [ -f "scaled/$gif.gif" ] && continue
    echo "scaling $gif.gif…"
    ffmpeg -hide_banner -loglevel error -y -i "$gif.gif" \
        -vf "scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
        "scaled/$gif.gif"
done
echo "done: $(du -sh scaled | cut -f1) in $(pwd)/scaled"
