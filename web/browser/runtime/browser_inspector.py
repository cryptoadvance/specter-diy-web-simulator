"""On-demand browser inspector bridge for the Specter simulator."""
import asyncio
import gc
import json
import os


_REQUEST_PATH = "/bridge/inspector-request"
_STATE_PATH = "/bridge/inspector-state.json"
_CANCEL_PATH = "/bridge/inspector-sensitive-cancelled"
_state = {"device": None, "enabled": False, "task": None}


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _remove(path):
    if _exists(path):
        os.remove(path)


def keystore_metadata(store):
    mnemonic = getattr(store, "mnemonic", None)
    root = getattr(store, "root", None)
    enc_secret = getattr(store, "enc_secret", None)
    return {
        "keystore.mnemonic": {"present": isinstance(mnemonic, str)},
        "keystore.root": {"present": root is not None,
                          "type": type(root).__name__ if root is not None else None},
        "keystore.enc_secret": {"loaded": enc_secret is not None,
                                 "bytes": len(enc_secret) if enc_secret is not None else 0},
        "bip39_seed": {"retainedAsKeystoreField": False,
                       "note": "Temporary local value during mnemonic derivation."},
    }


def inspection_data(device, request, include_sensitive=False):
    store = device.keystore
    screen = getattr(device.gui, "scr", None)
    data = {
        "requestId": int(request.get("requestId")),
        "allocatedBytes": gc.mem_alloc(),
        "freeBytes": gc.mem_free(),
        "network": device.network,
        "menu": getattr(device.current_menu, "__name__", "unknown"),
        "screen": type(screen).__name__ if screen is not None else "unavailable",
        "keystore": type(store).__name__ if store is not None else None,
        "keystoreObjects": keystore_metadata(store),
        "apps": [type(app).__name__ for app in device.apps],
    }
    if include_sensitive:
        mnemonic = getattr(store, "mnemonic", None)
        if isinstance(mnemonic, str) and not _exists(_CANCEL_PATH):
            data["sensitiveValues"] = {"keystore.mnemonic": mnemonic}
    return data


async def _report(device):
    while _state["enabled"]:
        try:
            with open(_REQUEST_PATH, "r") as request_file:
                request = json.loads(request_file.read())
            _remove(_REQUEST_PATH)
            data = inspection_data(device, request, request.get("includeSensitive") is True)
            if _state["enabled"]:
                with open(_STATE_PATH, "w") as state_file:
                    json.dump(data, state_file)
        except OSError:
            pass
        except asyncio.CancelledError:
            return
        except Exception as error:
            if _state["enabled"]:
                with open(_STATE_PATH, "w") as state_file:
                    json.dump({"error": str(error)}, state_file)
        if _state["enabled"]:
            await asyncio.sleep_ms(100)


def _start_task():
    if _state["enabled"] and _state["device"] is not None and _state["task"] is None:
        _state["task"] = asyncio.create_task(_report(_state["device"]))


def set_enabled(enabled):
    enabled = bool(enabled)
    if _state["enabled"] == enabled:
        return
    _state["enabled"] = enabled
    if enabled:
        _start_task()
        return

    task = _state["task"]
    _state["task"] = None
    if task is not None:
        task.cancel()
    _remove(_REQUEST_PATH)
    _remove(_STATE_PATH)
    _remove(_CANCEL_PATH)


def install(main):
    original = main.Specter.setup

    async def setup(device):
        _state["device"] = device
        _start_task()
        return await original(device)

    main.Specter.setup = setup
