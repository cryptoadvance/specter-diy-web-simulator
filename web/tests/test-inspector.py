"""Check inspector metadata does not copy or tokenize the mnemonic by default."""
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "browser" / "runtime" / "browser_inspector.py"
SPEC = importlib.util.spec_from_file_location("browser_inspector", MODULE_PATH)
inspector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspector)


class SensitiveText(str):
    def split(self, *args, **kwargs):
        raise AssertionError("normal inspection must not split the mnemonic")

    def encode(self, *args, **kwargs):
        raise AssertionError("normal inspection must not encode the mnemonic")


phrase = SensitiveText("fake abandon test phrase only")


class Store:
    mnemonic = phrase
    root = object()
    enc_secret = bytes(32)


class Device:
    keystore = Store()
    gui = type("Gui", (), {"scr": object()})()
    current_menu = type("Menu", (), {})
    network = "testnet"
    apps = []


inspector.gc.mem_alloc = lambda: 1024
inspector.gc.mem_free = lambda: 2048
ordinary = inspector.inspection_data(Device(), {"requestId": 1})
mnemonic_metadata = ordinary["keystoreObjects"]["keystore.mnemonic"]
assert mnemonic_metadata == {"present": True}
assert "sensitiveValues" not in ordinary

explicit = inspector.inspection_data(Device(), {"requestId": 2}, include_sensitive=True)
assert explicit["sensitiveValues"]["keystore.mnemonic"] is phrase
print("inspector mnemonic handling passed")
