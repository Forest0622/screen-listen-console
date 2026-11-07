# Screen Listen Console

A tiny macOS app that lets you **watch the screen of a Mac from a browser, read-only**, on the same local network.

The app is just a console: start/stop the service, show status, list the URLs to open, and show who has connected. **It never shows the live picture** and offers no mouse or keyboard control.

![platform](https://img.shields.io/badge/platform-macOS%2011%2B-lightgrey)
![python](https://img.shields.io/badge/runtime-Python%203-blue)
[![build](https://github.com/Forest0622/screen-listen-console/actions/workflows/build.yml/badge.svg)](https://github.com/Forest0622/screen-listen-console/actions/workflows/build.yml)

[中文说明](README.md)

## Screenshots

| Main window | Change credentials |
|---|---|
| ![main](docs/images/ui-main.png) | ![password](docs/images/ui-password.png) |

> Addresses and password in the screenshots are demo values (`192.168.1.23`, `demo-mac.local`, `Demo-Pass-2f9K`), not real network details.

## What it does

- Status box: service on/off, listening port, whether capture is healthy (with the age of the latest frame)
- Buttons: start service / stop service / refresh status
- Access URLs: `127.0.0.1`, the LAN IP, and the `.local` hostname — copy one or open it locally; the current username and password are printed right below them
- **Change credentials**: opens a small dialog to edit the username/password, or hit "random" to generate a 14-character password; saving takes effect immediately
- Access log: per-client IP, first/last visit, hit count, number of pages opened

## Credentials

- A **12-character random password is generated on first launch** (the alphabet omits look-alikes `l`, `I`, `0`, `O`) and stored in `~/.remote-view/config.json` with mode `600`. It is also printed once to `~/.remote-view/logs/service.log` in case you lose it.
- Two ways to change it, neither requires a restart:
  - click "Change credentials" in the app, or
  - edit `~/.remote-view/config.json` (`{"user": "admin", "password": "…"}`) directly.
- The server compares the file `mtime` on every request, so edits apply at once; the app re-reads it every 1.5 s, so the displayed password follows along.
- Constraints: username must not be empty, password at least 6 characters.

## How it works

Short version: **periodic screenshots + browser polling**. No macOS Screen Sharing, no VNC.

```
screencapture -x -t jpg  →  sips downscale to 1600 px wide / quality 55
        ↓ every second
  latest frame kept in memory  →  HTTP server (port 6080, Basic auth)
        ↓
  browser /           → viewer page (pause, zoom, fullscreen)
  browser /frame.jpg  → the latest frame
  browser /status     → JSON status
```

- The capture thread idles at one frame per 2 s and speeds up to 1 s while someone is viewing
- Failures back off exponentially (2 s … 60 s; permission errors at least 30 s) so the system prompt is not retriggered in a loop
- `/status` reports `ok` only if a frame was captured within the last 20 s, not merely because an old frame exists
- Client stats are written to `clients.json` (atomic replace, 3 s throttle); per-page detail goes to `access.log`

## Requirements

- macOS 11 or newer
- Python 3 (comes with the Command Line Tools: `xcode-select --install`)
- Screen Recording permission for the app (once per machine)

## Quick start

```bash
git clone https://github.com/Forest0622/screen-listen-console.git
cd screen-listen-console
./make-app.sh            # builds dist/屏幕监听控制.app
open "dist/屏幕监听控制.app"
```

1. Click "Start service"
2. Grant Screen Recording on first run: System Settings → Privacy & Security → Screen & System Audio Recording → add the app and toggle it on → quit the app (`⌘Q`) and reopen it
3. Wait until the status line says capture is healthy
4. The username and password for this run are shown under the access URLs; use them from any device on the same LAN

## Building a DMG

```bash
./make-dmg.sh            # builds dist/屏幕监听控制-安装包.dmg
```

The image contains the app, a symlink to `/Applications`, and a short readme. Drag the app in to install.

Two things will always happen on someone else's Mac — they are not bugs:

- **Gatekeeper blocks the first launch**: the default build is ad-hoc/self-signed, not notarized. Right-click the app → Open → Open again.
- **The other person must grant Screen Recording themselves**: TCC permission is per machine, it cannot travel with the bundle.

## Continuous integration

`.github/workflows/build.yml` compiles the app and builds the DMG on a GitHub macOS runner for every push/PR and uploads the artifact. Pushing a `v*` tag creates a Release with the DMG attached.

## Configuration

| Want to change | Where |
|---|---|
| Username / password | "Change credentials" in the app, or `~/.remote-view/config.json` |
| Port | `PORT` in `server.py` (also `RV_PORT`); change `PORT` in `Console.swift` too |
| Image size / quality | `TARGET_WIDTH`, `INTERVAL` in `server.py` |
| Data directory | defaults to `~/.remote-view`, override with `RV_DATA_DIR` |

## Known limitations (all measured, not laziness)

- **macOS Screen Sharing cannot be driven by noVNC**: it only offers Apple's private authentication (`RFB 003.889`, security types `30/33/36/35`) and none of the classic VNC password type 2, so third-party clients fail during the handshake. That is why this project uses screenshots + a web page instead.
- **No launchd agent or login item**: a process started by `launchd` (gui domain) never receives Screen Recording permission, so capture always fails and the user cannot grant it to that process. The app must be opened manually.
- **LAN only**: no tunneling or reverse proxy is included. For remote access, put it behind a VPN / Tailscale / your own reverse proxy, and change the password.
- **Read-only**: no mouse or keyboard control, no clipboard.

## Security notes

- HTTP Basic auth is **plaintext** on the LAN; do not use it on public Wi-Fi
- The service listens on `0.0.0.0:6080`; anyone who can reach the port sees the login prompt. A leaked password means a watched screen
- The password is random per machine rather than a hard-coded default, but the app and the config file display it in clear text — mind that when sharing screenshots
- `clients.json` / `access.log` contain client IPs; they are ignored by git (see `.gitignore`)

## Layout

```
server.py                 capture service (Python standard library only)
Console.swift             the console UI (AppKit, compiled by swiftc)
make-app.sh               build and assemble the .app
make-dmg.sh               build the DMG installer
assets/AppIcon.icns       icon
docs/使用说明.txt          end-user readme shipped inside the DMG (Chinese)
docs/images/              screenshots
.github/workflows/        CI build and release
```

## License

MIT
