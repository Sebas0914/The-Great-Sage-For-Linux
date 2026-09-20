# Great Sage

A Linux-first desktop AI companion with a 3D HUD, local voice pipeline, explicit tools, and a provider-neutral model layer.

## Current platform support

- **Linux / KDE Plasma / Wayland:** platform adapter, XDG GlobalShortcuts hotkey integration, KWin active-window bridge, application/path/URL launching, and KDE Spectacle screen capture.
- **Linux / X11:** platform adapter, configurable X11 global shortcut, active-window detection, and the same safe launcher interface.
- **Windows:** the existing Windows platform implementation remains available; Linux work is isolated behind the platform abstraction.

The application does **not** use a system-wide keylogger-style keyboard hook on Wayland. Global shortcuts use the desktop's GlobalShortcuts portal.

## Model architecture

Great Sage separates the model roles:

- **IA1 — fast:** ordinary conversation, simple explanations, straightforward actions, and routing decisions.
- **IA2 — complex:** substantial programming/debugging, project analysis, architecture, multi-step reasoning, and long synthesis.

With NVIDIA enabled, ambiguous requests are first classified by IA1 and then sent to the selected model. Clearly complex requests can go directly to IA2, while clearly simple requests can go directly to IA1.

### Provider modes

| Mode | Behavior |
|---|---|
| **NVIDIA_FIRST** | NVIDIA hosted API first; local provider is the fallback. |
| **LOCAL_FIRST** | Local provider first; NVIDIA is used only if the local provider fails before producing output. |
| **LOCAL_ONLY** | No remote AI provider is used. |

The global `GREAT_SAGE_LOCAL_ONLY=true` setting is a hard privacy stop.

## Tools and privacy

Tools are explicit and validated before execution. The model never receives an unrestricted shell.

Web tools are **disabled by default** and require both:

1. the global web-tools setting, and
2. permission from the active AI mode/settings.

`LOCAL_ONLY` always disables web tools.

Desktop tools use platform adapters rather than embedding Windows-only APIs in the core. On Linux, application launching is resolved through installed `.desktop` entries and paths/URLs are opened through the desktop's standard launchers.

## Voice pipeline

The intended local voice path is:

`speech -> faster-whisper -> Great Sage -> F5-TTS`

Speech recognition is local. F5-TTS is local and GPU acceleration is preferred.

## Install

Start with `INSTALL.md` for the complete setup and troubleshooting guide.

Typical Linux setup:

```bash
git clone https://github.com/Sebas0914/The-Great-Sage-For-Linux.git
cd The-Great-Sage-For-Linux

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

For NVIDIA-hosted AI, configure the NVIDIA API key through Chat Mode settings or the supported configuration mechanism. For fully local operation, configure the local provider and use `LOCAL_ONLY`.

No API key is stored in the repository.

## Project layout

```
great_sage/
  config/
    settings.py       central configuration
  core/
    chat_engine.py    conversation and tool loop
    tools.py          explicit tools and deterministic pre-routing
    ai_settings.py    provider selection, routing, privacy policy
    platform/         Linux/Windows desktop abstraction
  models/
    base.py            provider interface
    nvidia_provider.py NVIDIA fast/complex routing
    ollama_provider.py local provider
  voice/
    speech_to_text.py local faster-whisper STT
    f5_tts_engine.py  local F5-TTS output

check_*.py             CI regression/contract checks
.github/workflows/      Linux CI
```

## Validation

The repository contains focused contract checks for:

- Python compilation.
- HUD JavaScript and shaders.
- deterministic tool routing.
- NVIDIA fast/complex routing and local fallback.
- ChatEngine tool-call message shape.
- provider privacy/routing policy.
- Linux platform and KDE KWin bridge contracts.

CI runs these checks on the Linux development branch and pull requests.

## Known limitations

- A real KDE Wayland session is required to validate the desktop integrations end-to-end; CI validates their contracts but cannot reproduce the user's desktop session.
- The original transparent/click-through overlay host is Windows-specific. Linux currently uses the normal native HUD window rather than pretending the Win32 overlay works.
- Screen capture depends on KDE Spectacle being available.
- NVIDIA-hosted AI requires an API key and network access.
- F5-TTS and faster-whisper have substantial model/runtime dependencies.
- Image generation is not implemented.

## License and assets

Check the repository's license and asset-specific documentation before redistributing voice recordings or other third-party media. Pre-recorded character voice lines are not treated as original project code.
