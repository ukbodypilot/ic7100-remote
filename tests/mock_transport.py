"""Mock CIVTransport for tests.

Records every frame sent and replays canned responses based on the
(cmd, subcmd) tuple. Drop-in for `CIVTransport` — the IC7100 wrapper
only uses `build_frame`, `transact`, `send_raw`, `connect`,
`disconnect`, `mark_poll_thread`, and the `user_cmd_pending` event.
"""
import threading
from typing import Dict, List, Optional, Tuple

from ic7100ctl.civ import PREAMBLE, END, CTRL_ADDR, OK


class MockCIVTransport:
    def __init__(self, civ_addr: int = 0x88):
        self.addr = civ_addr
        self.ctrl_addr = CTRL_ADDR
        self.connected = True
        self.sent: List[bytes] = []
        self._responses: Dict[Tuple[int, Optional[int]], bytes] = {}
        self.user_cmd_pending = threading.Event()
        self._tls = threading.local()
        self.timeout = 1.0
        self.poll_timeout = 0.25

    # -- API parity --
    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def mark_poll_thread(self) -> None:
        self._tls.in_poll = True

    def build_frame(self, cmd: int, subcmd: Optional[int] = None,
                    data: bytes = b'') -> bytes:
        body = bytes([self.addr, self.ctrl_addr, cmd])
        if subcmd is not None:
            body += bytes([subcmd])
        body += data
        return PREAMBLE + body + END

    def transact(self, frame: bytes, timeout: Optional[float] = None) -> Optional[bytes]:
        self.sent.append(frame)
        # Parse frame for cmd/subcmd lookup
        cmd = frame[4]
        # Try (cmd, subcmd) first, then (cmd, None)
        if len(frame) > 6 and frame[5] not in (END[0],):
            key2 = (cmd, frame[5])
            if key2 in self._responses:
                return self._responses[key2]
        key1 = (cmd, None)
        if key1 in self._responses:
            return self._responses[key1]
        # Default response: a bare OK ack byte (FB). For "get" opcodes
        # (where the caller expects data echo with cmd byte first), use
        # set_response() to override.
        return OK

    def send_raw(self, frame: bytes) -> Optional[bytes]:
        return self.transact(frame)

    # -- Helpers for tests --
    def set_response(self, cmd: int, subcmd: Optional[int], body: bytes) -> None:
        """Canned response for the next transact() matching (cmd, subcmd).

        `body` is the bytes between the echoed cmd byte and FD — same shape
        the real transact() returns.
        """
        self._responses[(cmd, subcmd)] = body

    def last_frame(self) -> bytes:
        return self.sent[-1]

    def cmd_count(self) -> int:
        return len(self.sent)
