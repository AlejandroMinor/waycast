# waycast

Stream your Wayland desktop to any browser over the local network — built for the Meta Quest headset browser, but works anywhere. Nothing to install on the client.

Works on **any wlroots-based compositor**: Hyprland, Sway, river, Wayfire, etc. (it uses the `wlr-screencopy` protocol via `wf-recorder`, nothing compositor-specific).

## How it works

```
Wayland (wlroots) → wf-recorder (native MJPEG) → HTTP server → any browser
```

A single capture process, no ffmpeg subprocess per frame — `wf-recorder` encodes MJPEG directly for minimal latency. A tiny Python server (stdlib only) serves a `multipart/x-mixed-replace` MJPEG stream that any browser can open, including the one built into the Quest.

## Features

- **Low latency** — direct MJPEG, no transcoding, `TCP_NODELAY` + small send buffer so stale frames get skipped instead of queued.
- **Tunable** — `--fps`, `--quality`, `--scale`, `--chroma`, `--sharp` to trade quality for latency.
- **Live monitor switching** — pick the output from the web page, no reload, near-instant.
- **Password protected** — HTTP Basic auth, random password by default.
- **Single dependency** — `wf-recorder` (plus Python stdlib). No npm, no install on the headset.

## Requirements & installation

| | Needs |
|---|---|
| **OS** | Linux + Wayland on a wlroots compositor (Hyprland, Sway, river, labwc, Wayfire, …). **X11 is not supported**, and neither are **GNOME, KDE Plasma or COSMIC** — they don't implement `wlr-screencopy`, the protocol `wf-recorder` captures through. The distro doesn't matter, the compositor does. |
| **Capture** | `wf-recorder` (tested with 0.6.0; any version where `wf-recorder -L` works) |
| **Server** | Python ≥ 3.8 (stdlib only — nothing to `pip install`) |
| **Client** | Any browser that plays MJPEG: Chrome / Edge / Firefox and the Meta Quest browser |
| **Network** | Quest and PC on the same LAN; 5 GHz Wi-Fi recommended |

Install `wf-recorder` from your package manager (Python 3 is almost always already there):

| Distro | Command |
|---|---|
| Arch / Manjaro / CachyOS | `sudo pacman -S wf-recorder python` |
| Fedora | `sudo dnf install wf-recorder python3` |
| Debian 13+ / Ubuntu 24.04+ | `sudo apt install wf-recorder python3` |
| Alpine / Void / Nix | `apk add wf-recorder`, `xbps-install -S wf-recorder`, `nix shell nixpkgs#wf-recorder` |

> Old releases may ship a `wf-recorder` too old to list outputs (Ubuntu 22.04 has 0.2.x, which predates `-L`). In that case build it from source: https://github.com/ammen99/wf-recorder

Verify before running:

```bash
wf-recorder -L        # must print your outputs, e.g. DP-1, HDMI-A-1
python3 --version     # 3.8 or newer
```

`start.sh` does this check for you and aborts with a clear message if something is missing.

## How to run

```bash
./start.sh
```

The terminal prints the URL and an auto-generated password. Open the URL in the Quest browser:

```
http://<your-local-ip>:8080
```

The Quest and your PC must be on the same Wi-Fi network. `start.sh` checks the dependencies, kills any previous instance, and launches `stream.py`, forwarding any arguments you pass.

## Parameters

```bash
./start.sh [--fps N] [--quality N] [--port N] [--output NAME] [--scale N] [--chroma 420|422|444] [--sharp] [--password PASS]
```

| Parameter      | Default      | Description                                          |
|----------------|--------------|------------------------------------------------------|
| `--fps`        | `20`         | Frames per second                                    |
| `--quality`    | `4`          | MJPEG quality (quantizer): 1 = best/heavy, 31 = worst |
| `--port`       | `8080`       | HTTP port                                            |
| `--output`     | first monitor| Monitor to capture (e.g. `eDP-1`, `HDMI-A-1`)        |
| `--scale`      | native       | Downscale to this height in px (e.g. `720`). Less data = less latency |
| `--chroma`     | `420`        | Chroma subsampling: `420` default, `422` sharper color (+12% data), `444` full (= `--sharp`) |
| `--sharp`      | off          | Alias for `--chroma 444`: sharpest text at the cost of ~35% more data |
| `--password`   | random       | Access password for the stream                       |

If you don't pass `--password`, one is generated automatically and shown in the terminal at startup.

> **Security — local network only.** This serves over plain HTTP, so the password travels Base64-encoded but **unencrypted** (HTTP Basic auth). It's meant for your own trusted LAN. Don't expose port `8080` to the internet or forward it through your router — anyone on the path could read the stream and the password. If you ever need remote access, tunnel it (e.g. over SSH or a VPN) instead of opening the port.

> **Note on `--quality`:** the real control is the encoder's `qmin`/`qmax` quantizer. The `qscale` option many examples use is **ignored** by ffmpeg's MJPEG encoder — that's why changing it has no effect.

### `--quality` (image compression)

It's a quantizer, so it works inversely to what you'd expect:

| Value  | Quality      | Weight / latency        |
|--------|--------------|-------------------------|
| `1`    | best         | heavy, more latency     |
| `4`    | good (default) | balanced              |
| `8–10` | acceptable   | light, less latency     |
| `31`   | worst        | minimal                 |

Rule: **lower number = looks better but weighs more** (more latency). **Higher number = looks worse but runs smoother.**

### `--scale` (resolution)

The value is the final **height in pixels**; the width is computed automatically, keeping your screen's aspect ratio (it uses the ffmpeg filter `scale=-2:N`, where `-2` means "auto, even width"). For a native 1920x1080 screen:

| `--scale` | Actual resolution | Use                                   |
|-----------|-------------------|---------------------------------------|
| (unset)   | 1920x1080         | native, sharpest, most data           |
| `900`     | 1600x900          | slight reduction, good balance        |
| `720`     | 1280x720          | ~half the data, recommended for latency |
| `540`     | 960x540           | very light, noticeably soft           |
| `480`     | 854x480           | minimum, only if Wi-Fi is bad         |

Useful range: **480 to 1080**. Don't go above your native height (1080) — it adds no detail, just inflates the data. This is the strongest lever against latency because it attacks the root cause (amount of data), not just compression.

### `--chroma` (color sharpness)

JPEG stores chroma subsampled; that's what makes colored text edges and thin UI lines look soft. `--chroma` picks the mode wf-recorder encodes with (the pixel format passed as `-x`):

| Value  | Pixel format | Data vs `420` | Best for |
|--------|--------------|---------------|----------|
| `420`  | `yuvj420p`   | baseline (default) | general use |
| `422`  | `yuvj422p`   | **+12%**      | sharper colored text, small cost |
| `444`  | `yuvj444p`   | **+35%**      | crisp text (`--sharp` is an alias for this) |

Measured at 1920x1080, `--quality 4`: 284 KB → 318 KB → 383 KB per frame. More data means more latency over Wi-Fi, so prefer `420`/`422` unless text sharpness matters more than responsiveness.

### `--fps` (frames per second)

Each frame is a full JPEG, so the cost is direct: **double the fps = double the data per second** (`data/sec ≈ frame_size × fps`). It doesn't change how sharp the image looks, only how many frames you send.

| `--fps` | Feel                                   | Data (2560x1440, q4) |
|---------|----------------------------------------|----------|
| `10`    | choppy, fine for reading/static text   | ~20 Mbps |
| `15`    | smooth for desktop/code                | ~29 Mbps |
| `20`    | smooth, the default                    | ~40 Mbps |
| `25`    | smoother scrolling and mouse           | ~48 Mbps |
| `30`    | smooth motion, still light             | ~56 Mbps |

Useful range: **10 to 30**. Measured here: `wf-recorder` sustains 29.8 fps at `-r 30` (19.8 at `-r 20`), and the cost is mostly data, not CPU (226% vs 216% of a single core — the capture itself dominates). The figures above are for a mostly static desktop; **screen content matters more than anything else here** — a text-heavy screen at 20 fps costs ~70 Mbps and at 30 fps ~85 Mbps. Even the worst case stays around 15–20% of a 600 Mbps 5 GHz link.

### Combining the levers

All three reduce latency through different paths:

| Lever              | What it reduces            |
|--------------------|----------------------------|
| `--scale`          | pixels per frame (strongest) |
| `--fps`            | frames per second          |
| `--quality` (raise number) | weight of each frame (compression) |

Simple rule: if there's latency, lower **scale** first (most impact), then **fps**, and lastly raise the **quality** number.

### Where the latency goes

Measured on this machine (native capture, `--fps 20 --quality 4`, client on the same host):

| Stage | Time |
|---|---|
| `wf-recorder` capture + MJPEG encode (frame complete in the pipe) | **~85 ms** |
| server parse → publish → TCP send → client receive | **~1 ms** |
| browser decode/render | client side |

The server part is a rounding error: each frame is published as soon as its bytes arrive (no waiting for the next frame, no missed wakeups between frames) and the socket send buffer only holds 1–2 frames. So end-to-end latency is essentially **the capture floor plus the network**, and the levers below (`--scale`, `--quality`, `--fps`) are what actually move it.

### Live monitor switching

With more than one monitor connected, the web page shows **buttons centered at the top** to switch monitors without reloading or taking off the headset. The capture restarts on the fly, near-instantly (~0.2–0.3s), and works even on a static/idle monitor (no need to move anything on it first).

> The buttons only appear when 2+ monitors are detected. With a single monitor the bar is hidden so it doesn't get in the way. You can also pick the monitor at launch with `--output`.

Only one monitor is captured at a time (one `wf-recorder` process), so switching costs nothing extra in CPU or bandwidth — it just relaunches the capture on the chosen output.

### On-screen controls

All controls are nearly invisible by default and fade in on hover, so they don't obstruct the stream.

| Button | Position | Action |
|--------|----------|--------|
| Eye icon | top-left | Hide / show all controls (toggle) |
| Monitor buttons | top-center | Switch monitor (only shown with 2+ monitors) |
| Fullscreen icon | top-right | Enter fullscreen; changes to an exit icon while in fullscreen |

When controls are hidden via the eye button, the eye itself stays slightly visible so you can bring them back.

## Examples

Start from the row that matches what you're doing — these are the setups worth actually using:

| Use case | Command | Data (measured) |
|---|---|---|
| Everyday / balanced | `./start.sh` | ~40–70 Mbps |
| Reading, static text, weak Wi-Fi | `./start.sh --fps 15 --quality 6` | ~35 Mbps |
| **Programming from the headset** (crispest text) | `./start.sh --chroma 444 --quality 2 --fps 25` | ~70–125 Mbps |
| Maximum smoothness (scroll, video, motion) | `./start.sh --fps 30` | ~56–85 Mbps |
| Crowded / slow Wi-Fi | `./start.sh --scale 720 --fps 15 --quality 8` | ~10 Mbps |

*Measured at native 2560x1440 — a 1080p screen uses roughly half. The range is screen content: a mostly static desktop at the low end, a text-heavy screen at the high end (text is the expensive case for JPEG). Everything above fits a 600 Mbps 5 GHz link with room to spare.*

Pick your monitor with `--output` (or from the buttons in the page), and fix the password with `--password` so it doesn't change on every launch.

```bash
# Fixed password
./start.sh --password mysecret

# Maximum quality
./start.sh --quality 2 --fps 15

# More fluidity, reduced quality
./start.sh --fps 25 --quality 7

# External monitor
./start.sh --output HDMI-A-1

# Minimum latency (lower resolution + fewer fps + lighter quality)
./start.sh --scale 720 --fps 15 --quality 8

# Smooth balance if your Wi-Fi is good
./start.sh --scale 900 --fps 20 --quality 4
```

To list your monitor names:

```bash
wf-recorder -L
# or also:
hyprctl monitors
```

## Stopping

`Ctrl+C` in the terminal, or:

```bash
pkill -f waycast/stream.py
```

## Troubleshooting

**Black screen when opening the URL**
Run `./start.sh` from a terminal inside your Wayland session. Make sure `WAYLAND_DISPLAY` and `XDG_RUNTIME_DIR` are set — it won't work over SSH without display forwarding.

**High latency / the image keeps falling further behind**
With MJPEG over TCP, if Wi-Fi can't keep up the frames pile up and latency grows without bound. In order of impact:
1. `--scale 720` (or `--scale 900`) — lower the resolution, the biggest data saving.
2. `--quality 8` or higher — lighter frames.
3. `--fps 15` — fewer frames per second.
4. Move the PC closer to the router or use 5 GHz.

Typical combo: `./start.sh --scale 720 --fps 15 --quality 8`

**Low quality / blurry text**
Lower `--quality` (e.g. `--quality 2`) for better quality, and add `--chroma 422` (sharper colored text, +12% data) or `--sharp`/`--chroma 444` (crispest, +35% data). Note both increase data and latency.

**I want to capture a specific monitor**
Use `--output` with the monitor name, or switch live from the monitor buttons at the top of the page. Run `wf-recorder -L` to see the available outputs.

**Black screen / wrong monitor / it shows the same after switching**
This means more than one `wf-recorder` is capturing at once (leftover processes from previous runs). On wlroots, multiple simultaneous captures fight over the screen and the newest one gets no frames. `start.sh` now cleans up orphaned captures on launch, and the server kills its own capture on exit, so this shouldn't recur. To check/clean up manually:

```bash
pgrep -af "wf-recorder -c mjpeg"        # list capture processes (should be 1)
pkill -f "wf-recorder -c mjpeg -m mpjpeg"  # kill leftovers, then relaunch
```
