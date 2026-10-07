# waycast usage

Everything beyond the quick start in the [README](../README.md).

## Tuning latency vs quality

If the image falls behind, Wi-Fi can't keep up. Act in this order:

1. Lower `--scale` (`900`, `720`): fewer pixels, the strongest lever.
2. Lower `--fps` (`15`): data scales linearly with fps.
3. Raise `--quality` (`6`-`8`): lighter frames.

For sharper text, do the opposite: lower `--quality` and use `--chroma 422` or `444`.

| Scale | Resolution (from 1080p) |
|---|---|
| unset | 1920x1080 |
| `900` | 1600x900 |
| `720` | 1280x720 (about half the data) |
| `540` | 960x540 |

| Use case | Command | Data (2560x1440) |
|---|---|---|
| Balanced | `./start.sh` | ~40-70 Mbps |
| Reading, weak Wi-Fi | `./start.sh --fps 15 --quality 6` | ~35 Mbps |
| Programming | `./start.sh --chroma 444 --quality 2 --fps 25` | ~70-125 Mbps |
| Max smoothness | `./start.sh --fps 30` | ~56-85 Mbps |
| Slow Wi-Fi | `./start.sh --scale 720 --fps 15 --quality 8` | ~10 Mbps |

Text-heavy screens are the expensive case for JPEG; a 1080p screen uses roughly half. Everything above fits a 600 Mbps 5 GHz link.

## On-screen controls

Controls are almost invisible and fade in on hover.

| Control | Position | Action |
|---|---|---|
| Eye icon | top-left | Hide / show all controls |
| Monitor buttons | top-center | Switch monitor (only with 2+ monitors, ~0.2-0.3 s) |
| Fullscreen icon | top-right | Enter / exit fullscreen |

Only one monitor is captured at a time, so switching costs no extra CPU or bandwidth.

## How it works and where the latency goes

Capture is abstracted behind `CaptureBackend` ([backends.py](../backends.py)): `wlr` uses `wf-recorder` over `wlr-screencopy`, `x11` uses `ffmpeg -f x11grab`. `auto` picks `wlr` when `WAYLAND_DISPLAY` or `XDG_SESSION_TYPE=wayland` is set, otherwise `x11`. The server ([stream.py](../stream.py)) serves a `multipart/x-mixed-replace` MJPEG stream with `TCP_NODELAY` and a small send buffer, so stale frames are dropped instead of queued.

Measured at native capture, `--fps 20 --quality 4`, client on the same host:

| Stage | Time |
|---|---|
| Capture + MJPEG encode | ~85 ms |
| Server parse, publish, send, receive | ~1 ms |
| Browser decode / render | client side |

End-to-end latency is essentially the capture floor plus the network. Real E2E measured on this setup: ~60 ms average.

Not supported yet: GNOME, KDE Plasma and COSMIC, which need an xdg-desktop-portal backend.

## Troubleshooting

**Black screen on open**
Run `./start.sh` from a terminal inside your graphical session. `WAYLAND_DISPLAY` and `XDG_RUNTIME_DIR` must be set; it won't work over plain SSH.

**Black screen, wrong monitor, or switching shows the same monitor**
Leftover `wf-recorder` processes are fighting over the screen. `start.sh` cleans them on launch, but to do it by hand:

```bash
pgrep -af "wf-recorder -c mjpeg"           # should list only one
pkill -f "wf-recorder -c mjpeg -m mpjpeg"  # kill leftovers, then relaunch
```

**Latency keeps growing**
See "Tuning latency vs quality". Also move the PC closer to the router or use 5 GHz.

**Blurry text**
Use `--quality 2` with `--chroma 422` or `444`. This increases data and latency.

**Stop a stuck instance**

```bash
pkill -f waycast/stream.py
```

## Project layout and tests

| File | Role |
|---|---|
| `stream.py` | HTTP server: auth, MJPEG stream, monitor switching, UI |
| `backends.py` | Capture abstraction: `CaptureBackend`, `WlrBackend`, `X11Backend`, factory |
| `start.sh` | Dependency check, cleanup of previous runs, launches `stream.py` |
| `tests/` | `unittest` suite with fake `wf-recorder` / `ffmpeg` in `tests/bin/` |

```bash
python3 -m unittest discover -s tests
```
