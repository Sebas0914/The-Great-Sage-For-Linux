#!/usr/bin/env bash
set -u

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
RUN="$ROOT/run_hud.py"
PIDFILE="$ROOT/.great_sage.pid"
OVERLAY_PIDFILE="/tmp/great-sage-overlay.pid"

usage() { echo "Usage: $0 {install|start|run|stop|restart|show|hide|status}"; }

UNIT_SRC="$ROOT/systemd/great-sage.service"
UNIT_DST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/great-sage.service"

install_service() {
  mkdir -p "$(dirname "$UNIT_DST")"
  cp "$UNIT_SRC" "$UNIT_DST"
  systemctl --user daemon-reload
  systemctl --user enable --now great-sage.service
  echo "Great Sage installed and enabled for the graphical user session."
}

is_running() {
  [ -f "$PIDFILE" ] || return 1
  local pid
  pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start() {
  if [ -f "$UNIT_DST" ] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user start great-sage.service
    echo "Great Sage started through systemd."
    return 0
  fi
  if is_running; then show_overlay; echo "Great Sage is already running."; return 0; fi
  "$0" run >"$ROOT/great_sage_stdout.log" 2>&1 &
  echo $! >"$PIDFILE"
  disown || true
  echo "Great Sage started (PID $(cat "$PIDFILE"))."
}

run() {
  cd "$ROOT"
  [ -x "$PY" ] || { echo "Python environment not found: $PY" >&2; exit 1; }
  exec "$PY" "$RUN"
}

show_overlay() {
  if [ -f "$OVERLAY_PIDFILE" ]; then
    local opid
    opid="$(cat "$OVERLAY_PIDFILE" 2>/dev/null || true)"
    if [ -n "$opid" ] && kill -USR1 "$opid" 2>/dev/null; then return 0; fi
  fi
  if is_running && [ -x "$ROOT/.overlay-venv/bin/python" ]; then
    "$ROOT/.overlay-venv/bin/python" "$ROOT/overlay_window.py" >/dev/null 2>&1 &
  fi
}

hide_overlay() {
  if [ -f "$OVERLAY_PIDFILE" ]; then
    local opid
    opid="$(cat "$OVERLAY_PIDFILE" 2>/dev/null || true)"
    [ -n "$opid" ] && kill -USR2 "$opid" 2>/dev/null || true
  fi
}

stop() {
  if [ -f "$UNIT_DST" ] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop great-sage.service || true
  fi
  if is_running; then
    local pid
    pid="$(cat "$PIDFILE")"
    kill "$pid" 2>/dev/null || true
    for _ in {1..30}; do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
  fi
  if [ -f "$OVERLAY_PIDFILE" ]; then
    local opid
    opid="$(cat "$OVERLAY_PIDFILE" 2>/dev/null || true)"
    [ -n "$opid" ] && kill "$opid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
  echo "Great Sage stopped."
}

status() {
  if is_running; then echo "Great Sage: RUNNING (PID $(cat "$PIDFILE"))"; else echo "Great Sage: STOPPED"; fi
  if [ -f "$OVERLAY_PIDFILE" ]; then
    local opid
    opid="$(cat "$OVERLAY_PIDFILE" 2>/dev/null || true)"
    if [ -n "$opid" ] && kill -0 "$opid" 2>/dev/null; then echo "Raphael overlay: RUNNING (PID $opid)"; else echo "Raphael overlay: HIDDEN/NOT RUNNING"; fi
  else echo "Raphael overlay: HIDDEN/NOT RUNNING"; fi
}

case "${1:-}" in
  start) start ;; run) run ;; stop) stop ;; restart) 
    if [ -f "$UNIT_DST" ] && command -v systemctl >/dev/null 2>&1; then
      systemctl --user restart great-sage.service
    else
      stop; start
    fi
    ;;
  install) install_service ;;
  show) show_overlay ;; hide) hide_overlay ;; status) status ;;
  *) usage; exit 2 ;;
esac
