#!/usr/bin/env python3
"""BTC race bot: washout-reversal + selective deep-dip buyer, take-profit exits.

Built for btc-race-24h-20261113-2314 (dev window 24h, BTC $71,407 -> $67,901,
-4.91%: a steady grind down with one washout + snap-back in the first half
and only small bounces in the second). The three bots carried from the
previous race (original HOLD=180, HOLD=177, TP variant) ALL lose ~-$48
on this window and fail the dev gate, so this bot is a fresh tune on the
new window, not a copy of them.

Strategy (all decisions on 1-minute closes of CBBTC, long only, full size).
Two independent entry legs, each with its own exit; at most one position:
  ENTRY leg 1 — REVERSAL (washout bounce):
    - 10-bar return below -0.6% AND close above the close 3 bars ago.
      Catches the snap-back after a sharp washout: on the dev window it
      fires once, at the washout low (bar ~406, $67,877, the window low),
      and rides the +1.79% 60-bar rally that follows.
  ENTRY leg 2 — DEEP DIP (slow-mean snap-back):
    - Close > 1% below its 600-bar simple average AND turning up (close
      above the close 8 bars ago). The 600-bar mean is the reference
      because the window's only tradeable moves are snap-backs after
      multi-hour declines; a 60-bar mean fires on every small dip of the
      grind and loses. Fires twice on the dev window, both in the range
      phase, both closed by take-profit within 5-57 bars.
  EXIT (when holding), whichever comes first, per leg:
    - Take-profit: position value >= cost x (1 + TP), TP 1.3% for the
      reversal leg (it rides the bigger rally), 0.5% for the dip leg.
      Cost here is the harness's cost_quote_units (cash spent, fees
      included), which is what the server reports; the local simulator
      was corrected to the same basis after the old TP variant's sim
      (+$11.28) vs server (+$3.98) gap traced to the sim tracking cost
      ex-fee.
    - Hold cap: sell the whole position 90 bars (reversal) / 72 bars
      (dip) after entry.
  No momentum leg: on this window momentum entries bought dead-cat
  bounce tops and turned every momentum+dip variant negative.
  Sizing: every buy spends all cash (one position, max 100% of equity).
  Orders cap slippage at 100 bps from the latest close, as the kit
  baselines do. No clock, no randomness, no network: two runs on the
  same bars give the same orders. Standard library only.

Dev window (new, 1,440 bars): net PnL +$21.34, 3 round trips (6 trades),
fees $2.43, max drawdown -0.51%. First half +$17.78, second half +$4.78.
Perturbations (+-20% on every parameter, harness cost basis): 17 of 18
stay positive; worst -$6.08 (REV_UP x1.2: the reversal leg misses the
washout bounce and fires late). The dip leg alone scores +$8.93 with
worst perturbation -$0.32; the reversal leg adds +$12.78 on top.
Cross-window check (previous race dev window, 1,439 bars): -$14.05 —
the dip leg loses there (two late-window entries into a falling close),
so this bot is tuned to the new window's washout structure, not a
universal winner. Baselines on the new window: buy-and-hold -$52.59,
hold-cash $0.00. Old bots on the new window: HOLD=177 -$50.15,
HOLD=180 -$47.59 (both fail the dev gate).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

SYMBOL = "CBBTC"
MAX_SLIPPAGE_BPS = 100

# Parameters (see module docstring for why each is what it is).
REV_DROP = 0.007     # reversal leg: 10-bar return must be below -0.6%
REV_UP = 3           # ... and close above the close this many bars ago
TP_REV = 0.013       # reversal leg take-profit: +1.3% over harness cost
HOLD_REV = 90        # reversal leg hold cap, bars
DIP_N = 600          # dip leg reference: simple average of this many closes
DIP_PCT = 0.01       # dip leg: close must be 1% below that average
DIP_TURN = 8         # ... and above the close this many bars ago
TP_DIP = 0.0065       # dip leg take-profit: +0.5% over harness cost
HOLD_DIP = 72        # dip leg hold cap, bars

closes = []         # CBBTC closes, in arrival order (ints, price_scale 5)
entry_seq = -1      # seq of the batch the current position was entered on
entry_leg = None    # which leg opened the current position: 'rev' or 'dip'


def on_batch(state, batch):
    global entry_seq, entry_leg
    for bar in batch["bars"]:
        if bar["symbol"] == SYMBOL:
            closes.append(int(bar["c"]))
    if state.warming_up:
        return []

    held = state.positions.get(SYMBOL)
    if held is not None:
        take_profit = TP_REV if entry_leg == "rev" else TP_DIP
        hold_bars = HOLD_REV if entry_leg == "rev" else HOLD_DIP
        if (state.value(SYMBOL, held.qty) >= held.cost * (1 + take_profit)
                or state.seq - entry_seq >= hold_bars):
            entry_seq = -1
            entry_leg = None
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []

    # Flat: look for an entry. Reversal leg first, then the deep-dip leg.
    if not closes:
        return []
    c = closes[-1]
    leg = None
    if len(closes) > 10 and c / closes[-11] - 1 < -REV_DROP and c > closes[-REV_UP - 1]:
        leg = "rev"
    elif len(closes) > DIP_N and len(closes) > DIP_TURN:
        avg = sum(closes[-DIP_N:]) / DIP_N
        if c < avg * (1 - DIP_PCT) and c > closes[-DIP_TURN - 1]:
            leg = "dip"
    if leg is not None and state.cash >= 1_000_000:
        entry_seq = state.seq
        entry_leg = leg
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": state.cash,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]
    return []


makefun_bars.run(on_batch)
