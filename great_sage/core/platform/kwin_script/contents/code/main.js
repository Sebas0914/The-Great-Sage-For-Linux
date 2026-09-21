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
    const title = window ? (window.caption || "") : "";
    const pid = window ? Number(window.pid || 0) : 0;

    /*
     * Great Sage may not have started when KWin loads this script. A failed
     * D-Bus call must not terminate the KWin script, because the service can
     * appear later. The periodic reporter below will retry automatically.
     */
    try {
        callDBus(SERVICE, PATH, INTERFACE, "SetActiveWindow", title, pid);
    } catch (error) {
        // Service unavailable yet; keep the script alive and retry later.
    }
}

function reportCurrent() {
    report(workspace.activeWindow);
}

workspace.windowActivated.connect(function(window) {
    report(window);
});

/*
 * Report immediately and keep polling so startup order does not matter:
 * KWin can load the script before Great Sage, or Great Sage can start later.
 * The active window is only title/PID metadata; no keyboard input is observed.
 */
reportCurrent();

const retryTimer = setInterval(function() {
    reportCurrent();
}, 1000);
