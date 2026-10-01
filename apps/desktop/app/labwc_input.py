"""Setting the touchscreen's calibration on the labwc (Wayland) desktop, without root.

Under Wayland the compositor owns the input devices, so X's per-device property (x11_input)
has nothing to act on. labwc takes a libinput calibration matrix from its own config,
~/.config/labwc/rc.xml:

    <libinput>
        <device category="ADS7846 Touchscreen">
            <calibrationMatrix>a b c d e f</calibrationMatrix>
        </device>
    </libinput>

and re-reads that file on SIGHUP (what `labwc --reconfigure` sends), so a new calibration takes
effect on the next touch and also holds for every other program on the desktop. Everything
else in the file is kept — including Raspberry Pi OS's `<touch … mouseEmulation="yes"/>` line,
whose presence is what stops its autotouch script from rewriting the file at login.

Like x11_input, everything here fails soft: problems come back as an explanation.
"""

from __future__ import annotations

import os
import signal
import xml.etree.ElementTree as ET
from pathlib import Path


def running() -> bool:
    """labwc sets LABWC_PID for everything started in its session."""
    return bool(os.environ.get("LABWC_PID"))


def rc_path() -> Path:
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "labwc" / "rc.xml"


def _load(path: Path) -> ET.ElementTree:
    if not path.exists():
        return ET.ElementTree(ET.Element("labwc_config"))
    return ET.parse(path, ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))


def _namespace(root: ET.Element) -> str:
    """'{uri}' when the file declares a default namespace (Pi OS writes openbox's), else ''."""
    return root.tag[: root.tag.index("}") + 1] if root.tag.startswith("{") else ""


def _device(root: ET.Element, category: str, create: bool) -> ET.Element | None:
    ns = _namespace(root)
    for libinput in root.findall(f"{ns}libinput"):
        for device in libinput.findall(f"{ns}device"):
            if device.get("category") == category:
                return device
    if not create:
        return None
    libinput = root.find(f"{ns}libinput")
    if libinput is None:
        libinput = ET.SubElement(root, f"{ns}libinput")
    return ET.SubElement(libinput, f"{ns}device", category=category)


def matrix_text(matrix: list[float]) -> str:
    """The six affine terms, as labwc's calibrationMatrix wants them."""
    return " ".join(f"{float(v):.6f}" for v in matrix[:6])


def current_calibration(device_name: str) -> list[float] | None:
    """The calibration rc.xml holds for this device, if any."""
    try:
        root = _load(rc_path()).getroot()
    except (OSError, ET.ParseError):
        return None
    device = _device(root, device_name, create=False)
    element = None if device is None else device.find(f"{_namespace(root)}calibrationMatrix")
    if element is None or not element.text:
        return None
    try:
        values = [float(v) for v in element.text.split()]
    except ValueError:
        return None
    return values if len(values) == 6 else None


def set_calibration(matrix: list[float], device_name: str | None = None) -> str | None:
    """Writes the matrix into rc.xml and has labwc reload it. None on success, else why not."""
    if len(matrix) not in (6, 9):
        return f"a calibration matrix needs 9 values, got {len(matrix)}"
    path = rc_path()
    try:
        tree = _load(path)
    except ET.ParseError as e:
        return f"{path} isn't valid XML ({e}), so it was left alone"
    except OSError as e:
        return f"could not read {path}: {e}"

    root = tree.getroot()
    ns = _namespace(root)
    device = _device(root, device_name or "touch", create=True)
    element = device.find(f"{ns}calibrationMatrix")
    if element is None:
        element = ET.SubElement(device, f"{ns}calibrationMatrix")
    text = matrix_text(matrix)
    if element.text == text:
        return None  # already there, and labwc already read it

    element.text = text
    if ns:
        # Write the namespace back as the default one, not as an "ns0:" prefix on every tag.
        ET.register_namespace("", ns[1:-1])
    ET.indent(tree, space="\t")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        tree.write(temporary, encoding="unicode", xml_declaration=True)
        os.replace(temporary, path)
    except OSError as e:
        return f"could not write {path}: {e}"
    return _reconfigure()


def _reconfigure() -> str | None:
    try:
        os.kill(int(os.environ["LABWC_PID"]), signal.SIGHUP)
    except (KeyError, ValueError, ProcessLookupError, PermissionError) as e:
        return f"saved, but labwc couldn't be told to reload it ({e})"
    return None
