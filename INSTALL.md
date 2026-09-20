# Installing Great Sage

This fork is Linux-first. The application keeps the existing Windows
implementation, but the supported development path here is Linux.

## Linux / KDE Plasma

### Requirements

- Linux with a graphical desktop session.
- KDE Plasma is the primary Wayland target.
- Python 3.
- A working audio input/output device for voice features.
- NVIDIA GPU is recommended for F5-TTS performance.
- KDE Spectacle for Wayland screen capture.
- Network access only for NVIDIA-hosted AI or explicitly enabled web tools.

### 1. Clone the repository

```bash
git clone https://github.com/Sebas0914/The-Great-Sage-For-Linux.git
cd The-Great-Sage-For-Linux
```

### 2. Create the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If your distribution provides separate NVIDIA/CUDA PyTorch packages, install
the appropriate GPU-enabled PyTorch build before the remaining voice
dependencies. Do not assume a CUDA version from this document; use the
version supported by your installed driver.

### 3. Configure the model provider

Great Sage supports three routing policies:

- `NVIDIA_FIRST`: NVIDIA hosted AI first, local fallback.
- `LOCAL_FIRST`: local AI first, NVIDIA fallback after a provider failure
  before output begins.
- `LOCAL_ONLY`: local AI only.

The environment variable is:

```bash
export GREAT_SAGE_AI_MODE=nvidia_first
```

For a strict local-only session:

```bash
export GREAT_SAGE_LOCAL_ONLY=true
```

NVIDIA-hosted AI also needs an NVIDIA API key configured through the
application's AI settings. Never commit that key to Git.

### 4. Run

Use the application's Linux launcher/entry point described by the current
source tree. The first voice-model initialization can take substantially
longer than normal replies.

## KDE Wayland desktop integration

The Wayland adapter uses desktop APIs rather than a global keylogger.

- Global shortcuts use the XDG GlobalShortcuts portal.
- Active-window information is bridged through a KDE KWin script.
- Applications are launched through installed desktop entries.
- Paths and HTTP(S) URLs are opened through the desktop launcher.
- Screen capture uses KDE Spectacle.

The KWin bridge script is under:

```
great_sage/core/platform/kwin_script/
```

Install/enable that script through KDE's KWin scripting facilities when
running the active-window bridge. CI can validate the script contract, but
only a real KDE session can validate the complete D-Bus interaction.

## X11

On X11, Great Sage uses the X11 adapter and a configured XGrabKey shortcut.
The implementation only grabs the configured shortcut combination; it does
not monitor arbitrary keyboard input.

## Web tools

Web tools are disabled by default.

They require both explicit web-tool enablement and a mode that permits
online access. `LOCAL_ONLY` always disables them.

## Voice

Speech recognition uses local faster-whisper. F5-TTS is the preferred local
voice engine when configured.

If voice is disabled or its dependencies are unavailable, the model layer
can still be used for text interaction.

## Windows

The repository retains the Windows implementation. Windows-specific
dependencies and the original overlay setup are intentionally isolated from
the Linux platform layer. Follow the Windows-specific instructions already
provided by the application's Windows distribution if you are deploying
that platform.

## Troubleshooting

### Wayland shortcut does not activate

Confirm that the session is actually Wayland and that the desktop supports
the XDG GlobalShortcuts portal. Check the application log for portal startup
errors.

### Active window is unavailable

The KWin bridge requires the KDE script to be installed and active. This is
a desktop-session integration issue, not a model/provider issue.

### Screen capture fails

Confirm that `spectacle` is installed and that it can capture the screen
normally from KDE. The Linux adapter intentionally fails rather than
silently returning a nonexistent screenshot.

### NVIDIA provider does not answer

Check that the API key is configured, the selected NVIDIA model is available,
and the machine has network access. If routing is `NVIDIA_FIRST` and a local
fallback is configured, provider-level failures can fall back locally.

### Local-only unexpectedly uses a remote provider

Check both:

```bash
echo $GREAT_SAGE_LOCAL_ONLY
echo $GREAT_SAGE_AI_MODE
```

`GREAT_SAGE_LOCAL_ONLY=true` is intended to be a hard stop for remote AI,
independent of the UI-selected provider.

## Validation

CI checks Python compilation, the routing contract, NVIDIA routing/fallback,
tool-call message shape, provider privacy policy, JavaScript/shader syntax,
and the Linux/KWin platform contract.

A real KDE Wayland session is still required for end-to-end validation of
shortcuts, active-window D-Bus communication, and desktop capture.
