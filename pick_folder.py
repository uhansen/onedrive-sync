#!/usr/bin/python3
"""Native folder-picker helper, driven by the desktop's own FileChooser
portal (org.freedesktop.portal.Desktop / org.freedesktop.portal.FileChooser).

Deliberately NOT `#!/usr/bin/env python3`: this needs system PyGObject
(`gi`/`Gio`/`GLib`), which is only installed for the system interpreter at
/usr/bin/python3, not the mise-shimmed `python3` that other helpers in this
plugin use (and don't need, since they're pure stdlib). Service.qml invokes
this script with the explicit /usr/bin/python3 path for that reason.

Prints exactly one line on success: the absolute local path the user chose
in the native dialog. Prints nothing and exits non-zero on cancel, timeout,
or any portal/D-Bus error. Never reads or touches OneDrive tokens/secrets;
this is a plain, local, one-shot dialog wrapper.
"""
import os
import sys
import urllib.parse

try:
    import gi

    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib
except Exception:
    sys.exit(1)

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
PORTAL_FILECHOOSER_IFACE = "org.freedesktop.portal.FileChooser"
PORTAL_REQUEST_IFACE = "org.freedesktop.portal.Request"
TIMEOUT_SECONDS = 180


def uri_to_path(uri):
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "file":
        return None
    return urllib.parse.unquote(parsed.path)


def main():
    initial_dir = sys.argv[1] if len(sys.argv) > 1 else ""
    initial_dir = os.path.expanduser(initial_dir or "") or os.path.expanduser("~")
    if not os.path.isdir(initial_dir):
        initial_dir = os.path.expanduser("~")

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error:
        return 1

    loop = GLib.MainLoop()
    result = {"path": None}

    options = {
        "directory": GLib.Variant("b", True),
        "multiple": GLib.Variant("b", False),
        "current_folder": GLib.Variant("ay", os.fsencode(initial_dir) + b"\0"),
    }

    try:
        reply = bus.call_sync(
            PORTAL_BUS_NAME,
            PORTAL_OBJECT_PATH,
            PORTAL_FILECHOOSER_IFACE,
            "OpenFile",
            GLib.Variant("(ssa{sv})", ("", "Choose OneDrive copy destination", options)),
            GLib.VariantType.new("(o)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
    except GLib.Error:
        return 1

    request_path = reply.unpack()[0]

    def on_response(connection, sender_name, object_path, interface_name, signal_name, parameters):
        response_code, results = parameters.unpack()
        if response_code == 0:
            uris = results.get("uris") or []
            if uris:
                result["path"] = uri_to_path(uris[0])
        loop.quit()

    subscription_id = bus.signal_subscribe(
        PORTAL_BUS_NAME,
        PORTAL_REQUEST_IFACE,
        "Response",
        request_path,
        None,
        Gio.DBusSignalFlags.NONE,
        on_response,
    )

    def on_timeout():
        loop.quit()
        return False

    GLib.timeout_add_seconds(TIMEOUT_SECONDS, on_timeout)
    loop.run()
    bus.signal_unsubscribe(subscription_id)

    if result["path"] and os.path.isdir(result["path"]):
        print(result["path"])
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
