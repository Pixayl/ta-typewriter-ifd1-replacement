# Xerox 575 (Type Y92, TA SE-family): what makes the typewriter go ONLINE? + wiring details

Hi! Thank you for tweetwronger and the reverse-engineering Google Doc — they've been invaluable.

I'm driving a **Xerox 575 ("Type Y92", Made in Germany)** — a rebadged Triumph-Adler SE-family daisywheel (early model, no LCD, with an **ON LINE** key + LED) — through its 8-pin DIN port, aiming to use it as a printer like you did with the SE325.

## What I've established (matches your doc)

Using a multimeter + logic analyzer, my DIN pins map functionally exactly like your SE325 doc:

- **0 V (GND)**, and three supply pins: one reads **42 V** and one **12 V** unloaded (≈ your 35 V / 10 V under load), plus a **regulated 5 V** (confirmed: holds 4.9 V sourcing 20–50 mA — clearly the supply that powers the IFD1).
- One signal line **idles LOW** → consistent with **DTR** (your doc: DTR pulses HIGH ~1 ms after each byte; your `ready_latch` latches a HIGH-going pulse).
- Three remaining signal lines idle HIGH, high-impedance → **DSR / RX / TX**, but I can't tell which is which yet.

## What I've tried — all with *verified* signal delivery (checked with the logic analyzer)

- **RTS-style reset pulses** (FTDI RTS, 15 pulses, confirmed toggling the line 0↔5 V) applied to each of the three candidate lines in turn → **machine stays completely silent** (no `0x01` on any line, no LED).
- Holding each candidate line HIGH, then LOW (both polarities, in case of the inversion), then pressing ON LINE → nothing.
- Sending your init (`A0 00 / A1 00 / A4 00 / A2 00`) at 300–19200 baud into each line → nothing.
- Loading the 5 V rail (~50 mA, simulating the IFD1's power draw) → nothing.
- The machine **types fine locally**, but the **ON LINE key gives zero feedback** (no beep, no LED) and the port never emits anything (power-on = only mechanical self-test noise).

## Questions

1. **What actually makes the machine go online?** On your SE325, does the manual selection (TW/M + option 7) latch/light **without** the interface connected — or does the machine check some line state at the moment of the keypress? My ON LINE key does literally nothing, and I can't tell whether the key is simply dead (40-year-old switch) or gated on "host present".
2. **Does the RTS reset elicit the `0x01` at any time, or only once the machine is already online** via the manual selection?
3. Your doc says *“the pins on the cable are logically inverted.”* **How was inversion handled physically** — an inverter chip, the FT232R EEPROM invert options, or does the phrase mean something else? Concretely: do the machine's TX/RX idle LOW on the wire (inverted UART)?
4. Could you share the **exact host↔DIN wiring** you used — which adapter signal (TXD/RXD/RTS/DTR/CTS) went to which DIN pin, and where the Digispark `ready_latch` sits in the chain?

Any pointers hugely appreciated — with the pinout mapped I'm one detail away from a working setup. Thanks!
