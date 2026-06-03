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
- **Tunable** — `--fps`, `--quality`, `--scale`, `--sharp` to trade quality for latency.
- **Live monitor switching** — pick the output from the web page, no reload, near-instant.
- **Password protected** — HTTP Basic auth, random password by default.
- **Single dependency** — `wf-recorder` (plus Python stdlib). No npm, no install on the headset.

## Dependencies

- `wf-recorder` — Wayland screen capture (wlroots)
- `python3` — HTTP server (stdlib only, no extra packages)

```bash
# Arch / Manjaro / Hyprland
sudo pacman -S wf-recorder python3
```

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
./start.sh [--fps N] [--quality N] [--port N] [--output NAME] [--scale N] [--sharp] [--password PASS]
```

| Parameter      | Default      | Description                                          |
|----------------|--------------|------------------------------------------------------|
| `--fps`        | `20`         | Frames per second                                    |
| `--quality`    | `4`          | MJPEG quality (quantizer): 1 = best/heavy, 31 = worst |
| `--port`       | `8080`       | HTTP port                                            |
| `--output`     | first monitor| Monitor to capture (e.g. `eDP-1`, `HDMI-A-1`)        |
| `--scale`      | native       | Downscale to this height in px (e.g. `720`). Less data = less latency |
| `--sharp`      | off          | Sharper text (4:4:4) at the cost of ~2x data and more latency |
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

### `--fps` (frames per second)

Each frame is a full JPEG, so the cost is direct: **double the fps = double the data per second** (`data/sec ≈ frame_size × fps`). It doesn't change how sharp the image looks, only how many frames you send.

| `--fps` | Feel                                   | Data     |
|---------|----------------------------------------|----------|
| `10`    | choppy, fine for reading/static text   | minimal  |
| `15`    | smooth for desktop/code (recommended)  | low      |
| `20`    | smooth, the default                    | medium   |
| `25–30` | very smooth, for video/motion          | high, needs good Wi-Fi |

Useful range: **10 to 30**. On this setup `wf-recorder` realistically does up to ~25 fps; above that you gain little.

### Combining the levers

All three reduce latency through different paths:

| Lever              | What it reduces            |
|--------------------|----------------------------|
| `--scale`          | pixels per frame (strongest) |
| `--fps`            | frames per second          |
| `--quality` (raise number) | weight of each frame (compression) |

Simple rule: if there's latency, lower **scale** first (most impact), then **fps**, and lastly raise the **quality** number.

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
Lower `--quality` (e.g. `--quality 2`) for better quality, and add `--sharp` for crisp text (4:4:4 chroma). Note both increase data and latency.

**I want to capture a specific monitor**
Use `--output` with the monitor name, or switch live from the monitor buttons at the top of the page. Run `wf-recorder -L` to see the available outputs.

**Black screen / wrong monitor / it shows the same after switching**
This means more than one `wf-recorder` is capturing at once (leftover processes from previous runs). On wlroots, multiple simultaneous captures fight over the screen and the newest one gets no frames. `start.sh` now cleans up orphaned captures on launch, and the server kills its own capture on exit, so this shouldn't recur. To check/clean up manually:

```bash
pgrep -af "wf-recorder -c mjpeg"        # list capture processes (should be 1)
pkill -f "wf-recorder -c mjpeg -m mpjpeg"  # kill leftovers, then relaunch
```
