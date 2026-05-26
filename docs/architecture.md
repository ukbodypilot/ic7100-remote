# Architecture

`ic7100ctl` is a single Python process that owns the IC-7100's CI-V serial
port and serves a browser-based control panel over HTTP. There is no daemon
between the HTTP layer and the radio.

## Why direct CI-V, not hamlib

Hamlib (and its `rigctld` daemon) is the standard answer for "talk to a ham
radio from software". It's well-engineered for the case it was built for:
many disparate radios, many clients, an LCD-style command-at-a-time UX. It
is the wrong answer for a live-tracking web panel against one specific radio,
for four concrete reasons.

### 1. Hamlib serializes all access through one daemon

`rigctld` owns the serial port. Every client — your panel, your logger, your
poller — talks to `rigctld` over a socket. The daemon round-robins requests
to the radio. There is no abort-the-poll-for-a-user-command primitive: if
the daemon is mid-way through a settings sweep when you turn a knob, your
command queues behind the sweep. On a 19200 baud CI-V link a settings sweep
is ~16 round-trips at ~80 ms each — a worst-case 1.2 s of latency on a
single keystroke is routine.

`ic7100ctl` solves this in process. The poll thread and the HTTP request
handlers share one mutex on the transport, and the poll thread cooperates:
it calls `poll_settings()` with an abort `threading.Event`, and the HTTP
handler sets that event before grabbing the lock. The result is that a
multi-second poll cycle releases mid-flight when a user command arrives.

See `CIVTransport.user_cmd_pending` and the `abort` parameter on
`IC7100.poll_settings()` / `poll_fast()` in
[`ic7100ctl/radio.py`](../ic7100ctl/radio.py).

### 2. Hamlib's `set_freq` verifies by readback

By default `Hamlib::Rig::set_freq` writes the new frequency and then reads
it back to confirm. That's a defensible default for one-shot tuning. It is
fatal for a live VFO knob: you can't pipeline the next `set_freq` against
the previous ACK, because the previous call is still waiting on its
readback. The user-visible failure mode is the classic "stop touching it
before it commits" — the panel debounces to ~100 ms of idle before sending,
so what should feel like spinning a dial feels like typing in a frequency.

`ic7100ctl` issues `set_frequency` as a fire-and-wait-for-OK transaction
(no readback). The JS side runs a single-in-flight chase-target tuner (see
below). Each ACK gates the next send. The result is end-to-end ~25-30 ms
per step on the wire, with no debounce.

### 3. Hamlib swallows CI-V ACKs

Hamlib parses the CI-V `FB` (OK) / `FA` (NG) and folds them into its return
codes. Application-level interlocks — the kind of "did the radio actually
take my command?" check you want when composing a DATA-mode dance — hide
behind a generic error return. If the radio NGs because a TX-inhibit flag
is asserted, you find out via a logged warning, not a typed exception.

`ic7100ctl` exposes the raw response body. `_set_ok()` in
[`radio.py`](../ic7100ctl/radio.py) returns `True` only when the body starts
with `OK` (`0xFB`); anything else — NG, timeout, truncation — is `False`
and the caller decides what to do.

### 4. Composable application logic needs atomic ownership of the transport

The DATA-mode dance around PTT is the obvious case: in split mode, DATA
mode is per-VFO/mode, the radio's TX side is the inactive VFO, and you
have to set DATA on both VFOs (with a `swap_vfo` in between) before
keying — and undo all of it on key-down. The whole sequence has to run as
one atomic CI-V transaction, with no poller squeezing a meter read in
between. That's natural with an in-process mutex and impossible to
guarantee through a `rigctld` socket where some other client might inject
between any two of your calls.

## The fast-read pattern

`pyserial`'s blocking `read(N)` returns when either `N` bytes have arrived
or the configured timeout expires. The catch is the "or": if your CI-V
response is ~13 bytes but you asked for 64, `read(64)` floor-blocks for
the full timeout (typically 1 s) before returning the 13 bytes it has.
Every CI-V command then takes ~1 s end-to-end regardless of how fast the
radio actually replied.

`CIVTransport.transact()` in [`ic7100ctl/civ.py`](../ic7100ctl/civ.py)
sidesteps this by driving the read loop off `in_waiting`:

```python
deadline = time.monotonic() + _to
while time.monotonic() < deadline:
    avail = self._serial.in_waiting
    if avail:
        buf += self._serial.read(avail)
        # parse: FE FE E0 <addr> <data...> FD
        ...
        if end != -1:
            return buf[idx + 4:end]
    else:
        time.sleep(0.002)
```

The loop returns the moment a valid frame is parsed — typically ~23 ms
end-to-end on an IC-7100 at 19200 baud. The `time.sleep(0.002)` is a
busy-loop concession: 2 ms is short enough to be invisible at the latency
scale, long enough to not pin a CPU core.

## Lock fairness

Two threads contend for the transport mutex: the background poll thread
(which keeps the UI in sync with front-panel changes) and the HTTP server
threads (which carry user commands). Two mechanisms keep this fair.

**Per-thread timeout.** `CIVTransport.mark_poll_thread()` sets a
`threading.local` flag on the poller. `transact()` checks the flag and
uses `poll_timeout` (default 0.25 s) instead of `timeout` (default 1.0 s)
on poll-thread calls. A NG opcode mid-poll therefore can't pin the mutex
for a full second while a user command waits.

**Abort signal.** `IC7100.poll_settings(abort=...)` accepts a
`threading.Event` and checks it between each read. The HTTP handler sets
the event before calling its user command. The poll loop releases the
lock at the next 2 ms boundary, and the user command grabs it. The poll
that was aborted resumes on the next cycle from a fresh start — the
partially-filled cache is fine; nothing depends on a full sweep being
atomic.

There's also a 2 ms `time.sleep(0)`-style pause after each lock release
inside `poll_settings`, because otherwise the poll thread re-grabs the
mutex instantly and the user command's wait is for the full poll
duration regardless of the abort.

## Single-in-flight chase-target tuner (JS side)

The browser holds two values for each live-tuned control: the **target**
(what the UI thinks the value should be, updated on every wheel/drag
event) and the **in-flight** value (what was last sent to the server).
When an ACK comes back, the JS checks whether target == in-flight; if
not, it fires the next `POST` with the current target.

This means there is never more than one outstanding request per control,
and the request that's eventually sent is always the *latest* target the
user pointed at — intermediate values are dropped without ever hitting
the wire. No debounce timer, no commit-on-idle. The server side is
oblivious; the pattern is purely client-side and works because the server
serializes per-control commands behind the transport mutex anyway.

## Threading model

- One `http.server.ThreadingHTTPServer` — each request runs on its own
  thread. Handlers call into the `IC7100` instance, which calls
  `CIVTransport.transact()`, which takes the mutex.
- One background poll thread, tagged via `mark_poll_thread()`. Runs a
  fast cycle (freq/mode/PTT/S-meter/squelch_status) every ~250 ms, and
  the full settings sweep every Nth fast cycle. Both honor the abort
  event.
- One serial port. Owned by `CIVTransport`. All access through the
  mutex; no other entry points.

The mutex lives in `CIVTransport._lock`. It's the single point of
serialization in the system, and the only invariant the rest of the
architecture has to respect is "hold it for one frame's worth of
transact, then release."
