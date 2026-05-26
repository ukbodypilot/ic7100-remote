"""Command-line entrypoint for ic7100ctl."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .civ import CIVTransport
from .radio import IC7100, find_alsa_card


def _default_device() -> str:
    """Best-guess default serial device for the IC-7100 USB CAT port.

    The IC-7100's USB cable enumerates two CDC-ACM endpoints — one for CAT,
    one for the codec-bridge serial (rarely used). On most systems they
    appear as /dev/ttyUSB0 and /dev/ttyUSB1; the lower-numbered one is
    typically CAT. Users with multiple radios should pin a udev symlink.
    """
    candidates = ["/dev/ic7100", "/dev/ttyUSB0"]
    for c in candidates:
        if Path(c).exists():
            return c
    return "/dev/ttyUSB0"


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the HTTP server bound to a real radio."""
    transport = CIVTransport(
        port=args.device,
        baud=args.baud,
        civ_addr=args.civ_addr,
        timeout=args.timeout,
    )
    if not transport.connect():
        print(f"error: could not open {args.device}", file=sys.stderr)
        return 1

    radio = IC7100(transport)
    radio.connect()

    try:
        from .server import RadioServer  # late import — only needed for `serve`
    except Exception as e:
        print(f"error: HTTP server import failed: {e}", file=sys.stderr)
        return 2

    bridge = None
    if args.audio:
        try:
            from .webrtc import WebRTCBridge, AIORTC_AVAILABLE
        except Exception as e:
            print(f"error: --audio requested but webrtc deps missing: {e}",
                  file=sys.stderr)
            return 2
        if not AIORTC_AVAILABLE:
            print("error: aiortc not installed. "
                  "`pip install ic7100ctl[audio]`", file=sys.stderr)
            return 2
        card = args.alsa_card or find_alsa_card()
        if not card:
            print("error: no ALSA card found for IC-7100 USB codec. "
                  "Pass --alsa-card hw:N,0", file=sys.stderr)
            return 2
        print(f"audio: using ALSA card {card}", flush=True)
        bridge = WebRTCBridge(capture_device=card, playback_device=card)
        bridge.start()

    server = RadioServer(radio, host=args.host, port=args.port,
                         webrtc_bridge=bridge)
    server.start()
    print(f"ic7100ctl v{__version__} — http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    finally:
        server.stop()
        if bridge is not None:
            bridge.stop()
        transport.disconnect()
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """Probe a connected radio and print frequency / mode / model echo."""
    transport = CIVTransport(port=args.device, baud=args.baud,
                             civ_addr=args.civ_addr, timeout=1.0)
    if not transport.connect():
        print(f"error: could not open {args.device}", file=sys.stderr)
        return 1
    try:
        radio = IC7100(transport)
        radio.connect()
        print(f"device     : {args.device}")
        print(f"baud       : {args.baud}")
        print(f"civ addr   : 0x{args.civ_addr:02x}")
        print(f"frequency  : {radio.freq_hz} Hz" if radio.freq_hz else "frequency  : (unknown)")
        print(f"mode       : {radio.mode}" if radio.mode else "mode       : (unknown)")
        print(f"vfo        : {radio.active_vfo}")
        card = find_alsa_card()
        print(f"alsa card  : {card if card is not None else '(not found)'}")
    finally:
        transport.disconnect()
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Show resolved config paths and current settings file."""
    cfg_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    cfg_dir = Path(cfg_home) / "ic7100ctl"
    cfg_file = cfg_dir / "settings.json"
    print(f"config dir : {cfg_dir}")
    print(f"config file: {cfg_file}")
    print(f"exists     : {cfg_file.exists()}")
    if cfg_file.exists():
        print()
        print(cfg_file.read_text())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ic7100ctl",
        description="Fast, direct-CI-V web control panel for the Icom IC-7100.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # serve
    s = sub.add_parser("serve", help="Run the HTTP control panel")
    s.add_argument("--device", default=_default_device(),
                   help="Serial device for CAT (default: auto-detect)")
    s.add_argument("--baud", type=int, default=19200,
                   help="CI-V baud rate (default: 19200)")
    s.add_argument("--civ-addr", type=lambda x: int(x, 0), default=0x88,
                   help="IC-7100 CI-V address (default: 0x88)")
    s.add_argument("--timeout", type=float, default=1.0,
                   help="User-command CI-V timeout in seconds (default: 1.0)")
    s.add_argument("--host", default="127.0.0.1",
                   help="HTTP bind host (default: 127.0.0.1)")
    s.add_argument("--port", type=int, default=8080,
                   help="HTTP bind port (default: 8080)")
    s.add_argument("--audio", action="store_true",
                   help="Enable WebRTC audio (requires aiortc; "
                        "install with `pip install ic7100ctl[audio]`)")
    s.add_argument("--alsa-card", default=None,
                   help="ALSA card for the IC-7100 USB codec "
                        "(default: auto-detect via VID:PID 08bb:2901)")
    s.set_defaults(func=cmd_serve)

    # info
    i = sub.add_parser("info", help="Probe a connected radio and print state")
    i.add_argument("--device", default=_default_device())
    i.add_argument("--baud", type=int, default=19200)
    i.add_argument("--civ-addr", type=lambda x: int(x, 0), default=0x88)
    i.set_defaults(func=cmd_info)

    # config
    c = sub.add_parser("config", help="Show config paths + current settings")
    c.set_defaults(func=cmd_config)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
