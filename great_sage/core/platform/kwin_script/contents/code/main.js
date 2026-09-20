/*
 * Great Sage KDE/Wayland bridge.
 *
 * KWin exposes workspace.activeWindow to scripts. The script forwards only
 * the active window's title and PID to Great Sage's session D-Bus service.
 * No global keyboard hooks and no shell commands are used here.
 */

const SERVICE = "org.greatsage.KWinBridge";
const PATH = "/org/greatsage/KWinBridge";
const INTERFACE = "org.greatsage.KWinBridge";

function report(window) {
    if (!window) {
        callDBus(SERVICE, PATH, INTERFACE, "SetActiveWindow", "", 0);
        return;
    }

    const title = window.caption || "";
    const pid = Number(window.pid || 0);
    callDBus(SERVICE, PATH, INTERFACE, "SetActiveWindow", title, pid);
}

function reportCurrent() {
    report(workspace.activeWindow);
}

workspace.windowActivated.connect(report);
reportCurrent();
