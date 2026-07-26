# IFD-2 — a modern replacement for the Triumph-Adler / Royal **IF 600 / IFD 1** interface box

Turn a 1980s **Triumph-Adler** daisywheel typewriter (and its rebadges: **Xerox**, Royal, Adler)
into a computer printer, using a **Raspberry Pi Pico** instead of the long-lost original
interface box.

This repository documents a **complete reverse-engineering of the 8-pin DIN interface**
of a **Xerox 575 (Type Y92)** — pinout, handshake, command set and flow control — together
with working MicroPython firmware.

> The original TA interface boxes (IF 600, IFD 1, CB 1) are essentially unobtainable today.
> Without one, the DIN socket on the back of these machines is useless. This project makes
> that socket work again.

---

## Status

| Feature | State |
|---|---|
| Handshake / going online | ✅ works (still occasionally needs retries — see *Known issues*) |
| Printing arbitrary text | ✅ reliable, at the machine's full mechanical speed (~14 char/s) |
| Hardware flow control | ✅ via the machine's per-byte DTR acknowledge |
| Word wrap, line feed, carriage return | ✅ |
| Character pitch (condensed / normal) | ✅ |
| French accented characters | ✅ (`é è à ç ù`) |
| Reading the typewriter's keyboard | ❌ **not possible** — the machine is receive-only on this port |

---

## Hardware

### The 8-pin DIN socket (Xerox 575 / Type Y92)

Measured on this machine. **Pin numbering differs between models — verify yours before wiring.**

| Signal | Direction | Notes |
|---|---|---|
| **GND** | — | reference |
| **TX** | machine → host | the machine's transmit line (status bytes, echoes) |
| **RX** | host → machine | print data and commands |
| **DSR** | host → machine | host-present / reset line |
| **DTR** | machine → host | per-byte acknowledge (~1 ms pulse) |
| +5 V | — | powered the original interface box |
| +12 V, +42 V | — | ⚠️ **power rails — never connect these to logic** |

*(On this unit the two supply rails read 12 V and 42 V unloaded; the SE325 documentation
quotes 10 V and 35 V, i.e. the same rails measured under load.)*

### ⚠️ The critical electrical detail

The machine's inputs are **CMOS with a ~3.5 V threshold** (there is a CD4538 right behind the
connector). A 3.3 V push-pull output from a Pico is **not enough**, and adding a series
resistor changes the high level in non-obvious ways, because the machine's internal pull-up
drags the line toward 5 V through it.

**Solution: drive the machine's inputs as OPEN-DRAIN.** The Pico only ever pulls low; the
machine's own pull-up provides a clean 5 V high.

| Configuration | Low | High | Result |
|---|---|---|---|
| 1 kΩ series, push-pull | 1.00 V | 3.64 V | works, but random bit errors |
| 100 Ω series, push-pull | 0.12 V | 3.34 V | fails (below CMOS threshold) |
| **open-drain** | **0.3 V** | **5.0 V** | ✅ correct |

Because the RP2040's hardware UART is push-pull, **TX is bit-banged in software** on an
open-drain pin (see `_tx()` in the firmware); the hardware UART is used for RX only.

### Wiring (Raspberry Pi Pico)

| Pico | Mode | → machine |
|---|---|---|
| GND | — | GND |
| **GP0** | open-drain, software UART TX | **RX** (via a BAT85 Schottky, optional) |
| **GP1** | hardware UART0 RX | **TX** (1 kΩ series) |
| **GP2** | open-drain | **DSR** |
| **GP3** | input | **DTR** (1 kΩ series) |

The Pico is powered from USB. Only **GND** is shared with the machine — never tap its rails.

---

## Protocol

**4800 baud, 8N1, non-inverted.** All commands are **two bytes**.

### Session

1. Pulse **DSR** (brief high, idle low) → the machine answers **`0x01`**.
2. **Wait ~1 s.** The machine does not accept commands before that.
   (It also emits `0x01` spontaneously while idle, so a received `0x01` is not
   necessarily a reply to your pulse.)
3. Send, in order: `A0 00` (CLEAR), `A1 00` (START), `A4 00` (ENQ), `A2 00` (STX).
4. The machine **echoes the command bytes**, and answers ENQ with a status block —
   use the echo of `A2` to confirm the session is open.

The session **expires after a period of inactivity**; `ENQ` works as a heartbeat.

### Printing

| Command | Meaning |
|---|---|
| `<wheel index> <0x80 \| force>` | strike a character (`force` 0–63; bit 7 = advance; bit 6 = leftward) |
| `0x01 0x80` | space (blank strike with advance) |
| `0x82 0x03` | carriage return |
| `0x82 0x0F` | full position reset (carriage + wheel + ribbon) |
| `0xD0 <n>` | line feed |
| `0x84 <n>` | backspace |
| `0x80 <n>` | character pitch — width in units (`0x0F` normal, `0x0A` condensed) |
| `0xA3 00` + `0xA0 00` | go offline |

⚠️ These are **state transitions, not idempotent commands** — re-sending them to "retry"
will lock the machine up.

### Flow control

After **each received byte**, the machine pulses **DTR high for ~1 ms**, meaning
*"byte accepted, send the next one"*. When its buffer is full, that acknowledge is
**delayed** until a character has actually been struck — so the machine paces the host
by itself.

That 1 ms pulse is why a PC or a Linux SBC struggles here: it is far too short to catch
reliably from userspace over USB. A microcontroller catches it trivially. **This is the
whole reason for the Pico.**

Movement commands (carriage return, line feed) do **not** acknowledge — send those without
flow control and wait for the mechanics.

### Daisy wheel

Wheel positions are **1-based indices**, not ASCII. The table in the firmware is for a
**Prestige Cubic 10/12 (French, Xerox p/n 3R96686)**. It matches the SE325 wheel except for
ten positions: `12:^ 13:è 14:é 72:ì 74:¨ 75:◊ 80:ç 81:ù 82:ò 83:à`.

**Other wheels will differ** — use `cal()` in the firmware to print indices 1–100 and read
your own.

---

## Repository layout

```
pico/main.py         MicroPython firmware (the IFD-2 itself)
pico/send_from_pi.py host-side helper: send text to the Pico over USB
tools/               reverse-engineering scripts used along the way
docs/journal.md      full lab notebook: every measurement, dead end and fix
```

## Quick start

```bash
# flash MicroPython on the Pico, then:
mpremote fs cp pico/main.py :main.py
mpremote repl
```

```python
import main
main.start()
main.print_text("Hello from 1985")
```

## Known issues

- `start()` still needs several attempts on some power-up states. The machine emits
  spontaneous `0x01` bytes, so the host can mistake one for a reply and start the init
  at the wrong moment.
- Line spacing and line length are tuned for A4 with a condensed pitch; adjust
  `LF_CMD`, `LINE_UNITS` and `PITCH`.

## Credits

- [`binraker/tweetwronger`](https://github.com/binraker/tweetwronger) — prior art on the
  TA SE325, and the reverse-engineering notes that got this started.
- *ST Computer* magazine (1988), Gabriele 9009 articles, via
  [stcarchiv.de](https://www.stcarchiv.de/).

## License

MIT — see [LICENSE](LICENSE).
