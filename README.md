# waycast

Stream your Linux desktop to any browser over the local network. Built for the Meta Quest browser, works anywhere. Nothing to install on the client.

It captures with `wf-recorder` (wlroots compositors: Hyprland, Sway, river, labwc, Wayfire) or `ffmpeg` (X11) and serves MJPEG over HTTP with a password. Low latency (~60 ms measured on the same machine, before Wi-Fi and headset decoding), live monitor switching, Python stdlib only.

Setup is minimal: run one script and open a URL. No client app, no pairing.

## Requirements

| | Needs |
|---|---|
| **PC** | Linux with a wlroots compositor or an X11 session. GNOME, KDE Plasma and COSMIC are **not supported** (no `wlr-screencopy`) |
| **Capture tool** | `wf-recorder` (Wayland) or `ffmpeg` (X11) |
| **Server** | Python 3.8+ (no `pip install`) |
| **Client** | Any browser: Quest, Chrome, Edge, Firefox |
| **Network** | PC and headset on the same LAN, 5 GHz Wi-Fi recommended |

## Install

```bash
git clone https://github.com/AlejandroMinor/waycast.git
cd waycast
```

Arch:

```bash
sudo pacman -S wf-recorder python
```

Fedora:

```bash
sudo dnf install wf-recorder python3
```

Debian 13+ / Ubuntu 24.04+:

```bash
sudo apt install wf-recorder python3
```

`start.sh` checks the dependencies on launch and tells you what is missing.

## Start

```bash
./start.sh
```

The terminal prints the URL and a random password. Open it in the Quest browser:

```
http://<your-pc-ip>:8080
```

For example, if your PC is `192.168.1.50`:

```
http://192.168.1.50:8080
```

Find your IP with `ip -4 addr` (look for `inet 192.168...` on your Wi-Fi or Ethernet interface).

Stop with `Ctrl+C`. Some common setups:

```bash
./start.sh --password mysecret                    # fixed password
./start.sh --output HDMI-A-1                      # pick a monitor
./start.sh --scale 720 --fps 15 --quality 8       # weak Wi-Fi, less latency
./start.sh --chroma 444 --quality 2 --fps 25      # crispest text
```

> **Local network only.** It serves plain HTTP with Basic auth, so the password is not encrypted. Never expose the port to the internet; use SSH or a VPN for remote access.

## Options

```bash
./start.sh [--fps N] [--quality N] [--port N] [--output NAME] [--scale N]
           [--chroma 420|422|444] [--sharp] [--password PASS] [--backend auto|wlr|x11]
```

| Option | Default | Description |
|---|---|---|
| `--fps` | `20` | Frames per second (useful range 10-30) |
| `--quality` | `4` | JPEG quantizer: 1 = best/heaviest, 31 = worst/lightest |
| `--scale` | native | Final height in px (e.g. `720`); width keeps the aspect ratio |
| `--chroma` | `420` | Color subsampling: `420`, `422` (+12% data), `444` (+35% data) |
| `--sharp` | off | Alias for `--chroma 444` |
| `--output` | first monitor | Monitor to capture (`wf-recorder -L` or `hyprctl monitors` to list) |
| `--port` | `8080` | HTTP port |
| `--password` | random | Stream password |
| `--backend` | `auto` | `wlr` (wf-recorder), `x11` (ffmpeg x11grab), or detect from the session |

## Documentation

Once it runs, for tweaking it or when something goes wrong, everything is in [docs/USAGE.md](docs/USAGE.md):

| I want to... | Read |
|---|---|
| Reduce lag or get sharper text | [Tuning latency vs quality](docs/USAGE.md#tuning-latency-vs-quality) |
| Switch monitors or go fullscreen from the headset | [On-screen controls](docs/USAGE.md#on-screen-controls) |
| Understand how it works and where the latency comes from | [How it works](docs/USAGE.md#how-it-works-and-where-the-latency-goes) |
| Fix a black screen, wrong monitor or growing lag | [Troubleshooting](docs/USAGE.md#troubleshooting) |
| Know what each file does | [Project layout](docs/USAGE.md#project-layout-and-tests) |

## Development

```bash
python3 -m unittest discover -s tests
```

No extra dependencies; the tests use fake `wf-recorder` and `ffmpeg` from `tests/bin/`.
