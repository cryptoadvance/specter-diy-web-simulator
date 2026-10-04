"""Browser replacements for the Unix simulator's local hardware transports.

The QR UART and USB VCP use files under /bridge. The browser shell owns the
loopback WebSocket; no general socket or network API is exposed to the wallet.
"""
import os


class _CPU:
    A2 = "A2"
    A4 = "A4"
    G10 = "G10"
    C2 = "C2"
    C5 = "C5"


class Pin:
    IN = 0
    OUT = 1
    cpu = _CPU

    def __init__(self, *args, **kwargs):
        pass

    def on(self):
        # The scanner trigger is active-low. Expose only its transport state
        # to the browser shell; Specter's scan and QR parsing stay unchanged.
        try:
            os.remove("/bridge/scan-active")
        except OSError:
            pass

    def off(self):
        with open("/bridge/scan-active", "wb") as marker:
            marker.write(b"1")


class LED(Pin):
    pass


class UART:
    def __init__(self, name, *args, **kwargs):
        self.path = "/bridge/qr.bin" if name == "YA" else None

    def init(self, *args, **kwargs):
        pass

    def deinit(self):
        pass

    def write(self, data):
        return len(data)

    def any(self):
        if self.path is None:
            return 0
        try:
            return os.stat(self.path)[6]
        except OSError:
            return 0

    def read(self, size=None):
        if not self.any():
            return None
        with open(self.path, "rb") as stream:
            data = stream.read() if size is None else stream.read(size)
            remainder = stream.read() if size is not None else b''
        if remainder:
            with open(self.path, "wb") as stream:
                stream.write(remainder)
        else:
            os.remove(self.path)
        return data


class USB_VCP:
    RTS = 1
    CTS = 2
    input_path = "/bridge/usb-in.bin"
    output_path = "/bridge/usb-out.bin"

    def __init__(self, *args, **kwargs):
        pass

    def init(self, *args, **kwargs):
        pass

    def deinit(self):
        pass

    def any(self):
        try:
            return os.stat(self.input_path)[6]
        except OSError:
            return 0

    def read(self, size=None):
        if not self.any():
            return None
        with open(self.input_path, "rb") as stream:
            data = stream.read() if size is None else stream.read(size)
            remainder = stream.read() if size is not None else b""
        if remainder:
            with open(self.input_path, "wb") as stream:
                stream.write(remainder)
        else:
            os.remove(self.input_path)
        return data

    def write(self, data):
        if isinstance(data, str):
            data = data.encode()
        with open(self.output_path, "ab") as stream:
            stream.write(data)
        return len(data)


_usb_mode = None


def usb_mode(value=None):
    global _usb_mode
    if value is not None:
        _usb_mode = value
    return _usb_mode
