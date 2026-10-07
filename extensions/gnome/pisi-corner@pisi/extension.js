/*
 * PISI's corner - GNOME Shell extension (GNOME 45 and later)
 *
 * PISI (a desktop cat) keeps a little corner of things - a bed, a bowl, a
 * toy basket - standing at the bottom of the screen. GNOME Shell keeps
 * every click on its own panels and docks for itself, so where the corner
 * overlaps one (a dock at the bottom, say), its things can't be clicked or
 * dragged. This extension asks PISI (over D-Bus) where they are, takes the
 * clicks that land on them before the shell does, and passes clicks and
 * drags back. It draws nothing and does nothing while PISI
 * isn't running.
 */
import Clutter from "gi://Clutter";
import GLib from "gi://GLib";
import Gio from "gi://Gio";
import Meta from "gi://Meta";
import St from "gi://St";

import * as Main from "resource:///org/gnome/shell/ui/main.js";
import { Extension } from "resource:///org/gnome/shell/extensions/extension.js";

const GRAB_MAX_MS = 15000;    // a lost button-release must never leave the desktop grabbed

const NAME = "io.github.pisi.Companion";
const PATH = "/io/github/pisi/Companion";
const IFACE = `<node><interface name="io.github.pisi.Corner">
  <method name="Hotspots"><arg direction="out" type="s"/></method>
  <method name="Press"><arg direction="in" type="s"/><arg direction="in" type="i"/><arg direction="in" type="i"/></method>
  <method name="Move"><arg direction="in" type="i"/><arg direction="in" type="i"/></method>
  <method name="Release"><arg direction="in" type="i"/><arg direction="in" type="i"/></method>
  <method name="Attach"><arg direction="in" type="s"/></method>
  <method name="Detach"/>
  <signal name="HotspotsChanged"><arg type="s"/></signal>
</interface></node>`;
const CornerProxy = Gio.DBusProxy.makeProxyWrapper(IFACE);

class PisiCorner {
    // The stage sees every click on the panel first, before it decides who
    // gets it: a left click inside one of PISI's things is taken here and
    // passed to PISI; anything else goes on as usual. (Click areas stacked
    // as actors don't work: the corner is an override-redirect window, and
    // the shell picks window surfaces before any actor in that layer.)
    constructor() {
        this._spots = [];             // [{id, x, y, w, h}] in real pixels
        this._areas = [];             // input-region actors over them (see _place)
        this._proxy = null;
        this._signal = 0;
        this._watch = 0;
        this._stageWatch = 0;
        this._grabber = null;         // an invisible actor to hold the pointer with
        this._drag = null;            // {safety, last} while the button is down
        this._hover = false;
    }

    enable() {
        this._grabber = new St.Widget({ reactive: true, width: 1, height: 1, opacity: 0 });
        Main.uiGroup.add_child(this._grabber);
        this._stageWatch = global.stage.connect("captured-event", (_s, ev) => this._event(ev));
        this._watch = Gio.bus_watch_name(Gio.BusType.SESSION, NAME, Gio.BusNameWatcherFlags.NONE,
            () => this._connect(), () => this._disconnect());
    }

    disable() {
        if (this._proxy)
            this._proxy.DetachRemote(() => {});          // PISI takes its own clicks again
        if (this._watch)
            Gio.bus_unwatch_name(this._watch);
        this._watch = 0;
        this._disconnect();
        if (this._stageWatch)
            global.stage.disconnect(this._stageWatch);
        this._stageWatch = 0;
        if (this._grabber)
            this._grabber.destroy();
        this._grabber = null;
    }

    _connect() {
        this._disconnect();
        new CornerProxy(Gio.DBus.session, NAME, PATH, (proxy, error) => {
            if (error) {
                console.error("pisi-corner: " + error);
                return;
            }
            this._proxy = proxy;
            // from now on we take the clicks: PISI's corner window lets them through
            proxy.AttachRemote(Gio.DBus.session.get_unique_name(), () => {});
            this._signal = proxy.connectSignal("HotspotsChanged", (_p, _sender, [json]) => this._place(json));
            proxy.HotspotsRemote((result, err) => {
                if (!err)
                    this._place(result[0]);
            });
        });
    }

    _disconnect() {
        this._endDrag(null);
        if (this._proxy && this._signal)
            this._proxy.disconnectSignal(this._signal);
        this._proxy = null;
        this._signal = 0;
        this._place("[]");
    }

    _place(json) {
        try {
            this._spots = JSON.parse(json);
        } catch (e) {
            this._spots = [];
        }
        if (!this._spots.length)
            this._cursor(false);
        // the shell only hears clicks inside its input region (its panels and
        // chrome): add the things to it, the parts above the panel too
        for (const a of this._areas) {
            Main.layoutManager.removeChrome(a);
            a.destroy();
        }
        this._areas = this._spots.map(h => {
            const a = new St.Widget({ reactive: false, x: h.x, y: h.y, width: h.w, height: h.h });
            Main.layoutManager.addChrome(a, { affectsInputRegion: true, visibleInFullscreen: false });
            return a;
        });
    }

    _hit(x, y) {
        return this._spots.find(h => x >= h.x && x < h.x + h.w && y >= h.y && y < h.y + h.h);
    }

    _event(ev) {
        const type = ev.type();
        if (this._drag) {                                  // the button is down on a thing
            if (type === Clutter.EventType.MOTION) {
                const [x, y] = ev.get_coords();
                this._drag.last = [Math.round(x), Math.round(y)];
                this._proxy.MoveRemote(this._drag.last[0], this._drag.last[1]);
                return Clutter.EVENT_STOP;
            }
            if (type === Clutter.EventType.BUTTON_RELEASE) {
                this._endDrag(ev);
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        }
        if (!this._proxy || !this._spots.length)
            return Clutter.EVENT_PROPAGATE;
        if (type === Clutter.EventType.MOTION) {
            const [x, y] = ev.get_coords();
            this._cursor(!!this._hit(x, y));
            return Clutter.EVENT_PROPAGATE;
        }
        if (type === Clutter.EventType.LEAVE) {
            this._cursor(false);
            return Clutter.EVENT_PROPAGATE;
        }
        if (type !== Clutter.EventType.BUTTON_PRESS || ev.get_button() !== 1)
            return Clutter.EVENT_PROPAGATE;
        const [x, y] = ev.get_coords();
        const h = this._hit(x, y);
        if (!h)
            return Clutter.EVENT_PROPAGATE;
        this._proxy.PressRemote(h.id, Math.round(x), Math.round(y));
        // hold the pointer until the button comes up, wherever it goes (a drag)
        const grab = Main.pushModal(this._grabber);
        if (!grab) {
            this._proxy.ReleaseRemote(Math.round(x), Math.round(y));     // a plain click, then
            return Clutter.EVENT_STOP;
        }
        const safety = GLib.timeout_add(GLib.PRIORITY_DEFAULT, GRAB_MAX_MS, () => {
            if (this._drag)
                this._drag.safety = 0;           // (this timer is ending by itself)
            this._endDrag(null);
            return GLib.SOURCE_REMOVE;
        });
        this._drag = { grab, safety, last: [Math.round(x), Math.round(y)] };
        return Clutter.EVENT_STOP;
    }

    _endDrag(event) {
        const drag = this._drag;
        if (!drag)
            return;
        this._drag = null;
        if (drag.safety)
            GLib.source_remove(drag.safety);
        Main.popModal(drag.grab);
        if (this._proxy) {                       // PISI always hears the button come up
            const [x, y] = event ? event.get_coords() : drag.last;
            this._proxy.ReleaseRemote(Math.round(x), Math.round(y));
        }
    }

    _cursor(hand) {
        if (hand === this._hover)
            return;
        this._hover = hand;
        try {
            global.display.set_cursor(hand ? Meta.Cursor.POINTING_HAND : Meta.Cursor.DEFAULT);
        } catch (e) { /* cosmetic */ }
    }
}

export default class PisiCornerExtension extends Extension {
    enable() {
        this._corner = new PisiCorner();
        this._corner.enable();
    }

    disable() {
        this._corner?.disable();
        this._corner = null;
    }
}
