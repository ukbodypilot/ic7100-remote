# ic7100ctl

Fast, direct-CI-V web control panel for the Icom IC-7100. Unlike hamlib + WfView
or RemoteHams, it talks CI-V straight from the HTTP endpoint with no daemon in
the middle — so user keystrokes don't queue behind the background poller and
the live-tuner knobs actually track your finger.

<!-- Drop a real screenshot in at docs/screenshot.png and it will render here. -->
![Screenshot](docs/screenshot.png)

## What this is

A single-process Python server that owns the IC-7100's CI-V serial port and
serves a browser-based control panel. No daemons, no rigctld, no native client.

## What it isn't

- Not a hamlib backend. Doesn't speak rigctl.
- Not a multi-radio abstraction layer. IC-7100 only; see [Contributing](#contributing).
- Not a multi-user system in v0.1. Single operator, no auth.
- Not (yet) a multi-radio shack server. One IC-7100 per process.

## Quick start

```bash
# One-shot installer (clone first, or download the tarball)
git clone https://github.com/ukbodypilot/ic7100-remote.git
cd ic7100-remote
./install.sh

# Or do it by hand:
pip install --user .                                                # package
sudo install -m 644 udev/99-ic7100.rules /etc/udev/rules.d/         # /dev/ic7100 symlink
sudo udevadm control --reload && sudo udevadm trigger
install -m 644 systemd/ic7100ctl.service ~/.config/systemd/user/    # user systemd unit
systemctl --user daemon-reload
systemctl --user enable --now ic7100ctl

# Or just run it foreground:
ic7100ctl serve --device /dev/ic7100

# With WebRTC audio:
pip install --user ic7100ctl[audio]
ic7100ctl serve --device /dev/ic7100 --audio
```

Then point a browser at <http://localhost:8080/>.

## Features

- **23 ms CI-V command latency.** Direct serial, no rigctld serialization,
  `in_waiting`-driven read loop instead of `pyserial.read(N)`'s
  floor-blocking behaviour.
- **Live-tracking knobs** for Vol / Sql / PWR / MIC / AF and the frequency
  VFO. No debounce, no "stop touching it before it commits". UI commits the
  next value when the previous ACK lands.
- **Verified opcode coverage** with corrections vs the published Python libs:
  attenuator BCD value, memory write/clear ordering, IC-7100 vs IC-9100
  distinctions. See [docs/protocol.md](docs/protocol.md).
- **Split-mode aware DATA-mode toggle** around PTT. DATA mode is per-VFO/mode
  on the IC-7100; in split the radio's TX side is the inactive VFO, so the
  toggle hits both VFOs before keying.
- **USB audio codec auto-detect** by USB VID:PID (PCM2901, `08bb:2901`). The
  IC-7100's codec doesn't advertise itself as "ICOM" or "IC-7100" — keyword
  matching `arecord -l` finds nothing.
- **Browser panel.** No client install.
- **WebRTC audio (v0.2+).** RX from the radio's USB codec, TX from the
  browser's mic, both Opus over SRTP. Sub-100 ms latency on a LAN.
  Optional: `pip install ic7100ctl[audio]` then `--audio` on the CLI.
- **Persistence.** Settings survive endpoint restart via
  `~/.config/ic7100ctl/settings.json`.

## Hardware setup

- IC-7100 USB cable (rear of the body unit, type-B). The single USB cable
  carries both CAT (CI-V over a USB-serial bridge) and audio (PCM2901 codec)
  — no separate audio dongle required.
- A Linux box (this is Linux-only in v0.1). Anything that enumerates
  `/dev/ttyUSB*` and `/proc/asound/cardN/usbid`.
- Optional but recommended for bench TX testing: a dummy load. The endpoint
  has no built-in interlock to stop you keying into open air.

CI-V address defaults to `0x88` (IC-7100 factory default) at 19200 baud.

## Configuration

Settings live at `~/.config/ic7100ctl/settings.json` (or
`$XDG_CONFIG_HOME/ic7100ctl/settings.json`). Shape:

```json
{
  "port": "/dev/ttyUSB0",
  "baud": 19200,
  "civ_addr": 136,
  "http_bind": "127.0.0.1",
  "http_port": 8080,
  "alsa_card": "hw:1,0"
}
```

`alsa_card` is auto-detected from USB VID:PID at startup if absent.

### CLI

```
ic7100ctl serve  [--device PATH] [--baud N] [--civ-addr 0xNN]
                 [--timeout SECS] [--host ADDR] [--port N]
ic7100ctl info   [--device PATH] [--baud N] [--civ-addr 0xNN]
ic7100ctl config
```

`serve` is the main entrypoint. `info` probes a connected radio and prints its
frequency, mode, VFO, and detected ALSA card. `config` prints the resolved
settings path and dumps its current contents.

### Environment variables

| Variable | Meaning |
|---|---|
| `XDG_CONFIG_HOME` | Overrides settings file location root (default `~/.config`). |

## Limitations

- Linux only. The audio auto-detect path reads `/proc/asound`.
- IC-7100 only. No abstraction for IC-7300/IC-9100/etc. by design — see
  [docs/protocol.md](docs/protocol.md) for why mixing them is a footgun.
- Single operator in v0.1. No login, no auth, no multi-seat. Bind to
  `127.0.0.1` and front it with whatever you trust (SSH tunnel, Tailscale,
  reverse proxy with auth) if you want it off-host.
- Audio (v0.2+) needs aiortc + an Opus-capable browser (any current Firefox
  or Chromium). On the server side, `arecord`/`aplay` from `alsa-utils`.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the why-direct-CI-V deep
dive and the lock-fairness design. See [docs/protocol.md](docs/protocol.md)
for the opcode table and the corrections vs other published implementations.

## License

MIT. See [LICENSE](LICENSE).

## Contributing

Issues are welcome. PRs are welcome for bug fixes, opcode corrections,
documentation, and UI tightening.

Scope is strictly limited to the IC-7100. Don't bother sending a PR that adds
IC-7300 support — that's the rigctl/hamlib model and it's exactly what this
project exists not to be. Different Icom radios disagree on enough opcode
details (see e.g. attenuator BCD values, Main/Sub band, memory layout) that
abstracting them into one library is the source of most of the bugs this
project goes out of its way to avoid.
