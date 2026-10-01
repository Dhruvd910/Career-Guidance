#!/usr/bin/env python3
"""Sets up MAYA's echo canceller on this Pi's desktop (PipeWire). Run once, as the desktop user:

    python3 apps/desktop/setup_audio.py            # find the USB speaker and mic, install, restart audio
    python3 apps/desktop/setup_audio.py --dry-run  # only show what it found and would write
    python3 apps/desktop/setup_audio.py --remove   # undo

Needs PipeWire with its ALSA bridge (sudo apt install pipewire-alsa). The speaker is the USB
sound card's output; the microphone is a USB input on a card with no output (a dedicated USB
mic) — or say which with MAYA_SPEAKER_NODE / MAYA_MIC_NODE (PipeWire node names, from
`wpctl status` then `wpctl inspect <id>`). Run it again if the speaker or mic changes.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = Path.home() / ".config" / "pipewire" / "pipewire.conf.d" / "50-maya-echo-cancel.conf"
ASOUNDRC = Path.home() / ".asoundrc"
BEGIN, END = "# >>> MAYA (apps/desktop/setup_audio.py) >>>", "# <<< MAYA <<<"


def audio_nodes() -> list[dict]:
    dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, check=True).stdout)
    nodes = []
    for obj in dump:
        props = (obj.get("info") or {}).get("props") or {}
        if obj.get("type") == "PipeWire:Interface:Node" and props.get("media.class") in ("Audio/Sink", "Audio/Source"):
            nodes.append(props)
    return nodes


def find_devices() -> tuple[str, str]:
    nodes = [n for n in audio_nodes() if not str(n.get("node.name", "")).startswith("maya_")]
    usb = [n for n in nodes if n.get("device.bus") == "usb" or "usb" in str(n.get("node.name", ""))]
    sinks = [n for n in usb if n["media.class"] == "Audio/Sink"]
    sources = [n for n in usb if n["media.class"] == "Audio/Source"]
    cards_with_output = {n.get("alsa.card") for n in sinks}
    dedicated_mics = [n for n in sources if n.get("alsa.card") not in cards_with_output]
    speaker = os.environ.get("MAYA_SPEAKER_NODE") or (sinks[0]["node.name"] if sinks else None)
    mic = os.environ.get("MAYA_MIC_NODE") or ((dedicated_mics or sources)[0]["node.name"] if sources else None)
    if not speaker or not mic:
        sys.exit(f"Couldn't find a USB speaker ({speaker}) and microphone ({mic}). "
                 "Set MAYA_SPEAKER_NODE / MAYA_MIC_NODE.")
    return speaker, mic


def write_asoundrc() -> None:
    block = (HERE / "audio" / "asoundrc.maya").read_text().strip()
    text = ASOUNDRC.read_text() if ASOUNDRC.exists() else ""
    if BEGIN in text:
        start, end = text.index(BEGIN), text.index(END) + len(END)
        text = text[:start] + block + text[end:]
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
    ASOUNDRC.write_text(text)


def remove_asoundrc() -> None:
    if ASOUNDRC.exists() and BEGIN in (text := ASOUNDRC.read_text()):
        start, end = text.index(BEGIN), text.index(END) + len(END)
        rest = (text[:start] + text[end:]).strip()
        ASOUNDRC.write_text(rest + "\n") if rest else ASOUNDRC.unlink()


def restart_audio() -> None:
    subprocess.run(["systemctl", "--user", "restart", "pipewire.service", "pipewire-pulse.service",
                    "wireplumber.service"], check=True)


def canceller_running() -> bool:
    for _ in range(20):
        if any(n.get("node.name") == "maya_ec_source" for n in audio_nodes()):
            return True
        time.sleep(0.5)
    return False


def main() -> None:
    if "--remove" in sys.argv:
        CONFIG.unlink(missing_ok=True)
        remove_asoundrc()
        restart_audio()
        print("Removed MAYA's echo canceller.")
        return
    speaker, mic = find_devices()
    print(f"Speaker:    {speaker}\nMicrophone: {mic}")
    config = (HERE / "audio" / "maya-echo-cancel.conf.in").read_text()
    config = config.replace("@SPEAKER_NODE@", speaker).replace("@MIC_NODE@", mic)
    if "--dry-run" in sys.argv:
        print(f"\nWould write {CONFIG} and add MAYA's devices to {ASOUNDRC}.")
        return
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(config)
    write_asoundrc()
    restart_audio()
    if not canceller_running():
        sys.exit("The echo canceller didn't start — see `journalctl --user -u pipewire`.")
    print("MAYA's echo canceller is running: maya_speaker and maya_mic are ready.")


if __name__ == "__main__":
    main()
