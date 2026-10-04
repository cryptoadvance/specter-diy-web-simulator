# Specter DIY web simulator

Browser simulator tooling for Specter DIY. It provides the WebAssembly build,
simulated smartcard/SD-card/USB runtime, browser shell, provenance checks,
and tests used by
[`cryptoadvance/specter-diy`](https://github.com/cryptoadvance/specter-diy).

The firmware repository resolves simulator `main` once per build, checks out
that exact commit in its read-only build jobs, and runs the simulator scripts
from that checkout. The exact Specter source and simulator commits are recorded
in every browser build for provenance.

See [the simulator workflow and release notes](docs/browser-simulator.md) for
the repository contract and migration details.

The official browser build and pull-request previews are published by the
firmware repository at <https://cryptoadvance.github.io/specter-diy/>. To
connect a running simulator to wallet software, use the
[`cryptoadvance/specter-virtual-host`](https://github.com/cryptoadvance/specter-virtual-host)
local bridge and its [latest release](https://github.com/cryptoadvance/specter-virtual-host/releases/latest).
