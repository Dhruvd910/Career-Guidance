"""Setting the touchscreen's calibration on the running X server, without root.

libinput exposes a per-device "libinput Calibration Matrix" property that any X client may
change — this is exactly what `xinput set-prop` does. Doing it here through ctypes means no
extra package (xinput isn't installed on the Pi), no sudo, and no X restart: the new mapping
takes effect on the next touch. It lasts until X exits, so the app re-applies the saved
calibration every time it starts.

Everything here fails soft. With no X server (tests, SSH), or no touchscreen, the functions
return an explanation instead of raising — and Xlib's default error handler, which would
kill the whole process on a bad request, is replaced for the duration of each call.
"""

from __future__ import annotations

import ctypes
import os
import struct

MATRIX_PROPERTY = b"libinput Calibration Matrix"
XI_ALL_DEVICES = 0
PROP_MODE_REPLACE = 0
SUCCESS = 0


class _XIDeviceInfo(ctypes.Structure):
    _fields_ = [
        ("deviceid", ctypes.c_int),
        ("name", ctypes.c_char_p),
        ("use", ctypes.c_int),
        ("attachment", ctypes.c_int),
        ("enabled", ctypes.c_int),
        ("num_classes", ctypes.c_int),
        ("classes", ctypes.c_void_p),
    ]


_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


def float_to_item(value: float) -> int:
    """XInput2 properties of format 32 travel as 4-byte items (unlike core Xlib, which uses
    C longs); a FLOAT is its IEEE bits in one item — the same packing xinput uses."""
    return struct.unpack("<I", struct.pack("<f", value))[0]


def item_to_float(item: int) -> float:
    return struct.unpack("<f", struct.pack("<I", item & 0xFFFFFFFF))[0]


class _X:
    """A short-lived connection. Use as a context manager."""

    def __init__(self):
        self.x11 = ctypes.CDLL("libX11.so.6")
        self.xi = ctypes.CDLL("libXi.so.6")
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XInternAtom.restype = ctypes.c_ulong
        self.x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        self.x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.x11.XFree.argtypes = [ctypes.c_void_p]
        self.x11.XSetErrorHandler.restype = ctypes.c_void_p
        self.x11.XSetErrorHandler.argtypes = [ctypes.c_void_p]
        self.xi.XIQueryVersion.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        self.xi.XIQueryDevice.restype = ctypes.POINTER(_XIDeviceInfo)
        self.xi.XIQueryDevice.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self.xi.XIFreeDeviceInfo.argtypes = [ctypes.POINTER(_XIDeviceInfo)]
        self.xi.XIChangeProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_int,
        ]
        self.xi.XIGetProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int,
            ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        self.errors: list[int] = []
        self._handler = _ERROR_HANDLER(self._on_error)
        self.display = None
        self._previous_handler = None

    def _on_error(self, _display, _event) -> int:
        self.errors.append(1)
        return 0  # keep going; the default handler would exit the whole app

    def __enter__(self) -> "_X":
        name = os.environ.get("DISPLAY")
        if not name:
            raise OSError("no X display (DISPLAY is not set)")
        self.display = self.x11.XOpenDisplay(name.encode())
        if not self.display:
            raise OSError(f"could not open X display {name}")
        self._previous_handler = self.x11.XSetErrorHandler(ctypes.cast(self._handler, ctypes.c_void_p))
        major, minor = ctypes.c_int(2), ctypes.c_int(2)
        if self.xi.XIQueryVersion(self.display, ctypes.byref(major), ctypes.byref(minor)) != SUCCESS:
            raise OSError("the X server has no XInput2")
        return self

    def __exit__(self, *_exc) -> None:
        if self.display:
            self.x11.XSync(self.display, 0)
            self.x11.XCloseDisplay(self.display)
        if self._previous_handler is not None:
            self.x11.XSetErrorHandler(self._previous_handler)

    def atom(self, name: bytes) -> int:
        return self.x11.XInternAtom(self.display, name, 0)

    def devices(self) -> list[tuple[int, str]]:
        count = ctypes.c_int(0)
        info = self.xi.XIQueryDevice(self.display, XI_ALL_DEVICES, ctypes.byref(count))
        try:
            return [(info[i].deviceid, (info[i].name or b"").decode(errors="replace")) for i in range(count.value)]
        finally:
            if info:
                self.xi.XIFreeDeviceInfo(info)

    def get_floats(self, device_id: int, prop: int) -> list[float] | None:
        type_return, format_return = ctypes.c_ulong(0), ctypes.c_int(0)
        items, after = ctypes.c_ulong(0), ctypes.c_ulong(0)
        data = ctypes.POINTER(ctypes.c_ubyte)()
        status = self.xi.XIGetProperty(
            self.display, device_id, prop, 0, 64, 0, 0,  # AnyPropertyType
            ctypes.byref(type_return), ctypes.byref(format_return), ctypes.byref(items),
            ctypes.byref(after), ctypes.byref(data),
        )
        if status != SUCCESS or not data or format_return.value != 32:
            return None
        try:
            # libXi hands format-32 data back as 4-byte items (unlike core Xlib's longs).
            raw = ctypes.cast(data, ctypes.POINTER(ctypes.c_uint32))
            return [item_to_float(raw[i]) for i in range(items.value)]
        finally:
            self.x11.XFree(data)

    def set_floats(self, device_id: int, prop: int, values: list[float]) -> None:
        float_atom = self.atom(b"FLOAT")
        # XIChangeProperty (unlike XChangeProperty) takes format-32 data as 4-byte items.
        packed = (ctypes.c_uint32 * len(values))(*[float_to_item(v) for v in values])
        self.xi.XIChangeProperty(
            self.display, device_id, prop, float_atom, 32, PROP_MODE_REPLACE,
            ctypes.cast(packed, ctypes.c_void_p), len(values),
        )
        self.x11.XSync(self.display, 0)


def touchscreens() -> list[tuple[int, str]]:
    """(X device id, name) for every device carrying a libinput calibration matrix."""
    with _X() as x:
        prop = x.atom(MATRIX_PROPERTY)
        return [(dev_id, name) for dev_id, name in x.devices() if x.get_floats(dev_id, prop) is not None]


def set_calibration(matrix: list[float], device_name: str | None = None) -> str | None:
    """Applies a 9-value matrix. Returns None on success, or why it couldn't."""
    if len(matrix) != 9:
        return "a calibration matrix has 9 values"
    try:
        with _X() as x:
            prop = x.atom(MATRIX_PROPERTY)
            targets = [
                (dev_id, name) for dev_id, name in x.devices()
                if x.get_floats(dev_id, prop) is not None and (device_name is None or name == device_name)
            ]
            if not targets:
                return "no touchscreen with a libinput calibration matrix was found"
            for dev_id, _name in targets:
                x.set_floats(dev_id, prop, matrix)
            if x.errors:
                return "the X server rejected the calibration"
            applied = x.get_floats(targets[0][0], prop)
            if applied is None or any(abs(a - b) > 1e-4 for a, b in zip(applied, matrix)):
                return "the calibration didn't stick"
            return None
    except OSError as e:
        return str(e)
