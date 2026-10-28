/*  Kerf for After Effects: dockable panel (Window > Kerf.jsx after install into "Scripts/ScriptUI Panels").
    Native AE tools (anchor, layers, curves, shakes, stabilizer, zoom, align, sort, frame export, FX presets) run here
    in ExtendScript; AI tools (beats, quick mask, captions) call the local Kerf engine (python -m kerf serve).
    ExtendScript is ES3: no let/const, arrow functions or Array.map. */
(function kerfPanel(thisObj) {
    function home() { return $.getenv("KERF_HOME_DIR") || (Folder("~").fsName + "/.kerf"); }
    function locator() {  // the engine's locator (kerf/server.py LOCATOR): port, token file, helper
        var f = new File(home() + "/engine.json"), t;
        if (!f.exists) { return {}; }
        f.open("r"); t = f.read(); f.close();
        try { return eval("(" + t + ")"); } catch (e) { return {}; }  // written by our own engine
    }
    var S = { every: 1, amount: 120, zdur: 0.6, axis: "hv", amp: 28, freq: 11, rot: 1.5, dur: 0.45, decay: 0.7, flash: false };
    var status;

    // ------------------------------------------------------------ helpers
    function say(msg) { if (status) { status.text = msg; } }
    function comp() {
        var c = app.project.activeItem;
        if (!(c instanceof CompItem)) { throw new Error("Open a composition first."); }
        return c;
    }
    function layers() {
        var c = comp(), out = [], i;
        for (i = 0; i < c.selectedLayers.length; i++) { out.push(c.selectedLayers[i]); }
        if (!out.length) { throw new Error("Select one or more layers first."); }
        return out;
    }
    function act(name, fn) {
        return function () {
            app.beginUndoGroup("Kerf: " + name);
            try { var r = fn(); say(r || name + " done"); } catch (e) { say(name + ": " + e.message); }
            app.endUndoGroup();
        };
    }
    function q(s) {  // JSON string, ASCII-safe so Content-Length counts bytes correctly
        return '"' + String(s).replace(/[\\"]/g, "\\$&").replace(/\n/g, "\\n").replace(/\r/g, "\\r")
            .replace(/[^\x20-\x7e]/g, function (ch) { return "\\u" + ("000" + ch.charCodeAt(0).toString(16)).slice(-4); }) + '"';
    }
    function json(v) {
        var i, out, k;
        if (v === null || v === undefined) { return "null"; }
        if (typeof v === "number") { return isFinite(v) ? String(v) : "0"; }
        if (typeof v === "boolean") { return v ? "true" : "false"; }
        if (typeof v === "string") { return q(v); }
        if (v instanceof Array) { out = []; for (i = 0; i < v.length; i++) { out.push(json(v[i])); } return "[" + out.join(",") + "]"; }
        out = [];
        for (k in v) { if (v.hasOwnProperty(k)) { out.push(q(k) + ":" + json(v[k])); } }
        return "{" + out.join(",") + "}";
    }
    function token() {
        var f = new File(locator().token_file || home() + "/token");
        if (!f.exists) { throw new Error("Kerf engine not set up: start it once (start-kerf)."); }
        f.open("r"); var t = f.read(); f.close();
        return t.replace(/\s+/g, "");
    }
    function http(method, path, body, timeout) {
        var s = new Socket(), payload = body === undefined ? "" : json(body), raw = "", i;
        s.timeout = timeout || 3600;
        if (!s.open("127.0.0.1:" + (locator().port || 7878), "BINARY")) { throw new Error("Can't reach the Kerf engine: install Kerf (or run start-kerf), and enable Preferences > Scripting & Expressions > Allow Scripts to Write Files and Access Network."); }
        s.write(method + " " + path + " HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nX-Kerf-Token: " + token() +
                "\r\nContent-Length: " + payload.length + "\r\n\r\n" + payload);
        while (!s.eof) { raw += s.read(65536); }
        s.close();
        i = raw.indexOf("\r\n\r\n");
        var res = eval("(" + raw.substring(i + 4) + ")");  // our own engine on localhost, token-protected
        if (res && res.error) { throw new Error(res.error); }
        return res;
    }
    function sourcePath(l) {
        if (!(l.source instanceof FootageItem) || !l.source.file) { throw new Error(l.name + " is not a footage layer."); }
        return l.source.file.fsName;
    }
    function clipOf(l, c) {  // the layer as a Kerf timeline (source in/out in seconds)
        var a = l.inPoint - l.startTime, b = l.outPoint - l.startTime;
        return { fps: c.frameRate, width: c.width, height: c.height, name: c.name, playhead: c.time,
                 video: [[{ path: sourcePath(l), src_in: a, src_out: b, start: l.inPoint, enabled: true }]], audio: [[]] };
    }
    function importAbove(path, l, start) {
        var item = app.project.importFile(new ImportOptions(new File(path)));
        var nl = l.containingComp.layers.add(item);
        nl.startTime = start; nl.moveBefore(l);
        return nl;
    }
    function ease(prop, k, inf, side) {  // side: "in" | "out" | "both"; speed 0 = ease
        var n = prop.propertyValueType === PropertyValueType.TwoD_SPATIAL || prop.propertyValueType === PropertyValueType.ThreeD_SPATIAL ? 1 :
            (prop.value instanceof Array ? prop.value.length : 1), i, a = [], b = [];
        for (i = 0; i < n; i++) {
            a.push(new KeyframeEase(0, side === "out" ? 0.1 : inf));
            b.push(new KeyframeEase(0, side === "in" ? 0.1 : inf));
        }
        prop.setTemporalEaseAtKey(k, a, b);
    }
    function setAt(prop, t, v) { if (prop.numKeys) { prop.setValueAtTime(t, v); } else { prop.setValue(v); } }

    // ------------------------------------------------------------ MAIN tools
    function anchor(ax, ay) {
        var c = comp(), ls = layers(), i, l, r, A, P, sc, rot, na, dx, dy, cs, sn;
        for (i = 0; i < ls.length; i++) {
            l = ls[i];
            if (!l.sourceRectAtTime) { continue; }
            r = l.sourceRectAtTime(c.time, false);
            A = l.transform.anchorPoint.value; P = l.transform.position.value;
            sc = l.transform.scale.value; rot = l.transform.rotation.value * Math.PI / 180;
            na = [r.left + r.width * ax, r.top + r.height * ay];
            dx = (na[0] - A[0]) * sc[0] / 100; dy = (na[1] - A[1]) * sc[1] / 100;
            cs = Math.cos(rot); sn = Math.sin(rot);
            setAt(l.transform.anchorPoint, c.time, A.length > 2 ? [na[0], na[1], A[2]] : na);
            setAt(l.transform.position, c.time, P.length > 2 ? [P[0] + dx * cs - dy * sn, P[1] + dx * sn + dy * cs, P[2]]
                : [P[0] + dx * cs - dy * sn, P[1] + dx * sn + dy * cs]);
        }
        return "Anchor moved on " + ls.length + " layer(s)";
    }
    function addNull(parent) {
        var c = comp(), sel = [], i, x = 0, y = 0;
        for (i = 0; i < c.selectedLayers.length; i++) { sel.push(c.selectedLayers[i]); }
        var n = c.layers.addNull();
        n.name = parent ? "Kerf Parent" : "Kerf Null";
        if (parent && sel.length) {
            for (i = 0; i < sel.length; i++) { x += sel[i].transform.position.value[0]; y += sel[i].transform.position.value[1]; }
            n.transform.position.setValue([x / sel.length, y / sel.length]);
            for (i = 0; i < sel.length; i++) { sel[i].parent = n; }
        }
        return parent ? "Null parented to " + sel.length + " layer(s)" : "Null added";
    }
    function addSolid(adjust, hex) {  // hex "#rrggbb" from the HTML panel, else AE's colour picker
        var c = comp(), col = [0, 0, 0], picked;
        if (!adjust && hex) {
            picked = parseInt(String(hex).replace("#", ""), 16);
            col = [(picked >> 16 & 255) / 255, (picked >> 8 & 255) / 255, (picked & 255) / 255];
        } else if (!adjust) {
            picked = $.colorPicker(0x000000);
            if (picked < 0) { return "Cancelled"; }
            col = [(picked >> 16 & 255) / 255, (picked >> 8 & 255) / 255, (picked & 255) / 255];
        }
        var s = c.layers.addSolid(adjust ? [1, 1, 1] : col, adjust ? "Kerf Adjustment" : "Kerf Solid", c.width, c.height, c.pixelAspect);
        s.adjustmentLayer = !!adjust;
        return adjust ? "Adjustment layer added" : "Solid added";
    }
    function placeBeats() {
        var c = comp(), l = layers()[0], path = sourcePath(l), mp = c.markerProperty || l.property("Marker"), i, t, n = 0;
        say("Detecting beats…");
        var res = http("POST", "/run", { feature: "beat_markers", timeline: path, params: { music: path, every: S.every } });
        for (i = 0; i < res.markers.length; i++) {
            t = l.startTime + res.markers[i].t;
            if (t < l.inPoint || t > l.outPoint) { continue; }
            mp.setValueAtTime(c.markerProperty ? t : t, new MarkerValue(res.markers[i].name));
            n++;
        }
        return n + " beat markers · " + res.report.bpm + " BPM";
    }
    function clearBeats() {
        var c = comp(), mp = c.markerProperty, n = 0, i;
        if (!mp) { return "This After Effects version has no composition markers API"; }
        for (i = mp.numKeys; i >= 1; i--) { if (/^Beat/.test(mp.keyValue(i).comment)) { mp.removeKey(i); n++; } }
        return "Removed " + n + " beat markers";
    }
    function stabilize() {
        var c = comp(), ls = layers(), i, l, pc;
        for (i = 0; i < ls.length; i++) {
            l = ls[i];
            pc = c.layers.precompose([l.index], l.name + " (stabilized)", true);
            pc.layer(1).Effects.addProperty("ADBE SubspaceStabilizer");
        }
        return "Warp Stabilizer is analysing " + ls.length + " pre-comp(s)";
    }
    function scaled(s, k) { return s.length > 2 ? [s[0] * k, s[1] * k, s[2]] : [s[0] * k, s[1] * k]; }
    function zoom(dir, side) {
        var c = comp(), ls = layers(), i, s, p, k1, k2, k = S.amount / 100;
        for (i = 0; i < ls.length; i++) {
            p = ls[i].transform.scale; s = p.valueAtTime(c.time, false);
            p.setValueAtTime(c.time, dir === "in" ? s : scaled(s, k));
            p.setValueAtTime(c.time + S.zdur, dir === "in" ? scaled(s, k) : s);
            k1 = p.nearestKeyIndex(c.time); k2 = p.nearestKeyIndex(c.time + S.zdur);
            if (side === "out") { ease(p, k1, 85, "out"); } else { ease(p, k2, 85, "in"); }
        }
        return "Zoom " + dir + " (ease " + side + ") on " + ls.length + " layer(s)";
    }
    function quickMask() {
        var c = comp(), l = layers()[0], tl = clipOf(l, c), region = "", v, xs = [], ys = [], i, w, h, x0, y0;
        if (l.mask && l.mask.numProperties > 0) {  // draw a mask in AE = the region to cut out
            v = l.mask(1).maskShape.value.vertices; w = l.source.width; h = l.source.height;
            for (i = 0; i < v.length; i++) { xs.push(v[i][0]); ys.push(v[i][1]); }
            x0 = Math.min.apply(null, xs); y0 = Math.min.apply(null, ys);
            region = [x0 / w, y0 / h, (Math.max.apply(null, xs) - x0) / w, (Math.max.apply(null, ys) - y0) / h].join(",");
        }
        say("Cutting out the subject (offline AI)…");
        var res = http("POST", "/run", { feature: "quick_mask", timeline: tl, params: { clips: "all", region: region, model: "u2net_human_seg" } });
        importAbove(res.files[0], l, l.inPoint).name = l.name + " (Kerf cutout)";
        return "Cutout added above " + l.name + (region ? " (mask region)" : "");
    }
    // HTML panel: it runs the engine itself (async, no frozen AE) and only asks AE for these quick steps
    function clipInfo() {  // the selected layer as a Kerf timeline, plus a mask drawn on it as the cutout region
        var c = comp(), l = layers()[0], tl = clipOf(l, c), region = "", v, xs = [], ys = [], i, w, h, x0, y0;
        if (l.mask && l.mask.numProperties > 0) {
            v = l.mask(1).maskShape.value.vertices; w = l.source.width; h = l.source.height;
            for (i = 0; i < v.length; i++) { xs.push(v[i][0]); ys.push(v[i][1]); }
            x0 = Math.min.apply(null, xs); y0 = Math.min.apply(null, ys);
            region = [x0 / w, y0 / h, (Math.max.apply(null, xs) - x0) / w, (Math.max.apply(null, ys) - y0) / h].join(",");
        }
        return json({ timeline: tl, path: tl.video[0][0].path, name: l.name, region: region });
    }
    function addMarkers(list) {  // beat times relative to the layer's source
        var c = comp(), l = layers()[0], mp = c.markerProperty || l.property("Marker"), i, t, n = 0;
        for (i = 0; i < list.length; i++) {
            t = l.startTime + list[i].t;
            if (t < l.inPoint || t > l.outPoint) { continue; }
            mp.setValueAtTime(t, new MarkerValue(list[i].name));
            n++;
        }
        return n + " beat marker(s) on " + l.name;
    }
    function addLayer(path, name, start) {
        var l = layers()[0];
        importAbove(path, l, start === undefined || start === null ? l.inPoint : start).name = name;
        return name + " added above " + l.name;
    }
    // Result steps (kerf/features.py steps) that After Effects can perform
    function importFiles(paths) {
        var i;
        for (i = 0; i < paths.length; i++) { app.project.importFile(new ImportOptions(new File(paths[i]))); }
        return "Imported " + paths.length + " file(s) into the project";
    }
    function placeFile(path, name, at) {
        var c = comp(), nl = c.layers.add(app.project.importFile(new ImportOptions(new File(path))));
        nl.startTime = at; nl.name = name;
        return name + " added at " + at.toFixed(2) + " s";
    }
    function compMarkers(list) {
        var c = comp(), i;
        for (i = 0; i < list.length; i++) { c.markerProperty.setValueAtTime(list[i].t, new MarkerValue(list[i].name)); }
        return "Added " + list.length + " chapter marker(s)";
    }
    // Scripts hub: the user's own installed scripts and ScriptUI panels, run from Kerf (nothing is copied or bundled)
    function listScripts() {
        var base = Folder.appPackage.fsName + "/Scripts", dirs = [[base, false], [base + "/ScriptUI Panels", true]], out = [], i, j, fs, n;
        for (i = 0; i < dirs.length; i++) {
            fs = new Folder(dirs[i][0]).getFiles(function (x) { return x instanceof File && /\.jsx(bin)?$/i.test(x.name); });
            for (j = 0; j < fs.length; j++) {
                n = decodeURI(fs[j].name);
                if (/^Kerf\.jsx$/i.test(n)) { continue; }
                out.push({ name: n.replace(/\.jsx(bin)?$/i, ""), path: fs[j].fsName, panel: dirs[i][1] });
            }
        }
        return json(out);
    }
    function runScript(path) {
        var f = new File(path);
        if (!f.exists) { throw new Error("That script is no longer installed"); }
        $.evalFile(f);  // ScriptUI panels open as floating windows when run this way
        return "Opened " + decodeURI(f.name).replace(/\.jsx(bin)?$/i, "");
    }
    function frameExport() {
        var c = comp(), f = new File(Folder.desktop.fsName + "/" + c.name + " " + c.time.toFixed(2) + "s.png");
        c.saveFrameToPng(c.time, f);
        return "Saved " + f.fsName;
    }
    function sortProject() {
        var bins = { Comps: [], Footage: [], Images: [], Audio: [], Solids: [], Other: [] }, root = app.project.rootFolder, i, it, ext, k, f, n = 0;
        var existing = {};
        for (i = 1; i <= root.numItems; i++) { if (root.item(i) instanceof FolderItem) { existing[root.item(i).name] = root.item(i); } }
        for (i = root.numItems; i >= 1; i--) {
            it = root.item(i);
            if (it instanceof FolderItem) { continue; }
            if (it instanceof CompItem) { k = "Comps"; }
            else if (it.mainSource instanceof SolidSource) { k = "Solids"; }
            else {
                ext = it.file ? it.file.name.toLowerCase().replace(/^.*\./, "") : "";
                k = /^(wav|mp3|aac|m4a|aif|aiff|flac|ogg)$/.test(ext) ? "Audio" : /^(png|jpe?g|tiff?|psd|ai|gif|bmp|exr|webp|svg)$/.test(ext) ? "Images"
                    : it.hasVideo ? "Footage" : "Other";
            }
            bins[k].push(it);
        }
        for (k in bins) {
            if (!bins.hasOwnProperty(k) || !bins[k].length) { continue; }
            f = existing[k] || app.project.items.addFolder(k);
            for (i = 0; i < bins[k].length; i++) { bins[k][i].parentFolder = f; n++; }
        }
        return "Sorted " + n + " item(s)";
    }

    // FX presets: effect stack (values + keyframes + expressions) as JSON in the engine's preset store
    var SKIP = {};
    SKIP[PropertyValueType.NO_VALUE] = 1; SKIP[PropertyValueType.CUSTOM_VALUE] = 1; SKIP[PropertyValueType.MARKER] = 1;
    SKIP[PropertyValueType.SHAPE] = 1; SKIP[PropertyValueType.TEXT_DOCUMENT] = 1; SKIP[PropertyValueType.LAYER_INDEX] = 1; SKIP[PropertyValueType.MASK_INDEX] = 1;
    function ser(p, l) {
        var o, i, c;
        if (p.propertyType === PropertyType.PROPERTY) {
            if (SKIP[p.propertyValueType] || !p.isModified) { return null; }
            o = { m: p.matchName };
            if (p.numKeys) { o.k = []; for (i = 1; i <= p.numKeys; i++) { o.k.push([p.keyTime(i) - l.inPoint, p.keyValue(i)]); } } else { o.v = p.value; }
            if (p.expressionEnabled) { o.x = p.expression; }
            return o;
        }
        o = { m: p.matchName, c: [] };
        for (i = 1; i <= p.numProperties; i++) { c = ser(p.property(i), l); if (c) { o.c.push(c); } }
        return o;
    }
    function deser(target, o, l) {
        var i, j, p, c;
        for (i = 0; i < (o.c || []).length; i++) {
            c = o.c[i];
            try {
                p = target.property(c.m);
                if (!p) { continue; }
                if (c.c) { deser(p, c, l); continue; }
                if (c.k) { for (j = 0; j < c.k.length; j++) { p.setValueAtTime(l.inPoint + c.k[j][0], c.k[j][1]); } }
                else if (c.v !== undefined) { p.setValue(c.v); }
                if (c.x) { p.expression = c.x; }
            } catch (e) { /* a value this property refuses: keep going */ }
        }
    }
    function copyFx(name) {
        var l = layers()[0], fx = l.property("ADBE Effect Parade"), out = [], i;
        for (i = 1; i <= fx.numProperties; i++) { out.push(ser(fx.property(i), l)); }
        if (!out.length) { return l.name + " has no effects"; }
        http("POST", "/fx/save", { name: name, chain: { host: "aftereffects", effects: out } });
        return "Saved “" + name + "” (" + out.length + " effects)";
    }
    function applyFx(name) {
        var chain = http("POST", "/fx/get", { name: name }), ls = layers(), i, j, e;
        if (chain.host !== "aftereffects") { return "“" + name + "” was saved from Premiere: its effects can't be applied in AE"; }
        for (i = 0; i < ls.length; i++) {
            for (j = 0; j < chain.effects.length; j++) {
                try { e = ls[i].Effects.addProperty(chain.effects[j].m); deser(e, chain.effects[j], ls[i]); } catch (err) { /* plug-in missing */ }
            }
        }
        return "Applied " + chain.effects.length + " effect(s) to " + ls.length + " layer(s)";
    }

    // ------------------------------------------------------------ curves: value (keyframe ease) and speed (time remap)
    var VALUE = { "Ease out": ["out", 85], "Ease in": ["in", 85], "Ease in/out": ["both", 70], "Snappy": ["both", 95], "Linear": ["linear", 0] };
    function valueCurve(name) {
        var c = comp(), props = c.selectedProperties, i, j, k, p, n = 0, mode = VALUE[name];
        for (i = 0; i < props.length; i++) {
            p = props[i];
            if (p.propertyType !== PropertyType.PROPERTY || !p.selectedKeys || !p.selectedKeys.length) { continue; }
            for (j = 0; j < p.selectedKeys.length; j++) {
                k = p.selectedKeys[j];
                if (mode[0] === "linear") { p.setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR); }
                else { p.setInterpolationTypeAtKey(k, KeyframeInterpolationType.BEZIER); ease(p, k, mode[1], mode[0]); }
                n++;
            }
        }
        return n ? name + " on " + n + " keyframe(s)" : "Select keyframes in the timeline first";
    }
    function speedCurve(kind) {
        var ls = layers(), i, l, tr, a, b, k, sp;
        for (i = 0; i < ls.length; i++) {
            l = ls[i];
            if (!l.canSetTimeRemapEnabled) { continue; }
            l.timeRemapEnabled = true;
            tr = l.property("ADBE Time Remapping");
            for (k = tr.numKeys - 1; k > 1; k--) { tr.removeKey(k); }
            a = 1; b = tr.numKeys;
            var lin = KeyframeInterpolationType.LINEAR, bez = KeyframeInterpolationType.BEZIER;
            tr.setInterpolationTypeAtKey(a, kind === "linear" ? lin : bez); tr.setInterpolationTypeAtKey(b, kind === "linear" ? lin : bez);
            if (kind === "ease_in") { ease(tr, a, 85, "out"); }
            else if (kind === "ease_out") { ease(tr, b, 85, "in"); }
            else if (kind === "ease_in_out") { ease(tr, a, 75, "out"); ease(tr, b, 75, "in"); }
            else if (kind === "speedramp") {  // fast → slow in the middle → fast
                tr.setValueAtTime((tr.keyTime(a) + tr.keyTime(b)) / 2, (tr.keyValue(a) + tr.keyValue(b)) / 2);
                k = tr.nearestKeyIndex((tr.keyTime(a) + tr.keyTime(b)) / 2);
                sp = 0.15 * Math.abs(tr.keyValue(b) - tr.keyValue(a)) / Math.max(0.01, tr.keyTime(b) - tr.keyTime(a));
                tr.setTemporalEaseAtKey(k, [new KeyframeEase(sp, 90)], [new KeyframeEase(sp, 90)]);
            }
        }
        return "Speed " + kind.replace(/_/g, " ") + " on " + ls.length + " layer(s)";
    }

    // ------------------------------------------------------------ shakes (expression + slider controls: stays editable)
    function slider(l, name, v) {
        var fx = l.Effects.property(name) || l.Effects.addProperty("ADBE Slider Control");
        fx.name = name; fx.property(1).setValue(v);
    }
    function shake() {
        var c = comp(), ls = layers(), i, l, ax = S.axis;
        var mx = (ax === "vertical" || ax === "scale") ? 0 : 1, my = (ax === "horizontal" || ax === "scale") ? 0 : 1;
        var mr = (ax === "all" || ax === "custom") ? 1 : 0, ms = (ax === "scale" || ax === "all") ? 1 : 0;
        var env = 'var s=effect("Kerf Shake Start")(1),d=effect("Kerf Shake Duration")(1),k=effect("Kerf Shake Decay")(1),' +
                  'f=effect("Kerf Shake Frequency")(1),a=effect("Kerf Shake Amplitude")(1),tt=time-s,e=(tt<0||tt>d)?0:Math.pow(1-tt/d,1+3*k);seedRandom(index,true);';
        for (i = 0; i < ls.length; i++) {
            l = ls[i];
            slider(l, "Kerf Shake Start", c.time); slider(l, "Kerf Shake Duration", S.dur); slider(l, "Kerf Shake Decay", S.decay);
            slider(l, "Kerf Shake Frequency", S.freq); slider(l, "Kerf Shake Amplitude", S.amp); slider(l, "Kerf Shake Rotation", S.rot);
            l.transform.position.expression = env + "var w=wiggle(f,a*e)-value;value+(value.length>2?[w[0]*" + mx + ",w[1]*" + my + ",0]:[w[0]*" + mx + ",w[1]*" + my + "]);";
            l.transform.rotation.expression = env + "value+" + mr + '*(wiggle(f,effect("Kerf Shake Rotation")(1)*e)-value);';
            l.transform.scale.expression = env + "var p=" + ms + "*Math.abs(Math.sin(2*Math.PI*f*time))*a/4*e;value+(value.length>2?[p,p,0]:[p,p]);";
        }
        if (S.flash) {
            var adj = c.layers.addSolid([1, 1, 1], "Kerf Flash", c.width, c.height, c.pixelAspect);
            adj.adjustmentLayer = true;
            var ex = adj.Effects.addProperty("ADBE Exposure2").property(3);
            ex.setValueAtTime(c.time, 2.5); ex.setValueAtTime(c.time + 0.15, 0);
        }
        return "Shake (" + ax + ") on " + ls.length + " layer(s): tweak the Kerf Shake sliders in Effect Controls";
    }

    // ------------------------------------------------------------ align & distribute (comp-relative, rotation ignored)
    function bounds(l, t) {
        var r = l.sourceRectAtTime(t, false), A = l.transform.anchorPoint.valueAtTime(t, false), P = l.transform.position.valueAtTime(t, false),
            sc = l.transform.scale.valueAtTime(t, false);
        return { x: P[0] + (r.left - A[0]) * sc[0] / 100, y: P[1] + (r.top - A[1]) * sc[1] / 100, w: r.width * sc[0] / 100, h: r.height * sc[1] / 100, P: P };
    }
    function moved(P, dx, dy) { return P.length > 2 ? [P[0] + dx, P[1] + dy, P[2]] : [P[0] + dx, P[1] + dy]; }
    function align(mode) {
        var c = comp(), ls = layers(), i, b, dx, dy, items = [];
        for (i = 0; i < ls.length; i++) { if (ls[i].sourceRectAtTime) { items.push([ls[i], bounds(ls[i], c.time)]); } }
        if (mode.indexOf("dist") === 0) {
            if (items.length < 3) { return "Distribute needs 3 or more layers"; }
            var hz = mode === "dist_h", ctr = function (x) { return hz ? x.x + x.w / 2 : x.y + x.h / 2; };
            items.sort(function (p, q2) { return ctr(p[1]) - ctr(q2[1]); });
            var c0 = ctr(items[0][1]), c1 = ctr(items[items.length - 1][1]);
            for (i = 1; i < items.length - 1; i++) {
                b = items[i][1];
                var d = c0 + (c1 - c0) * i / (items.length - 1) - ctr(b);
                setAt(items[i][0].transform.position, c.time, hz ? moved(b.P, d, 0) : moved(b.P, 0, d));
            }
            return "Distributed " + items.length + " layers";
        }
        for (i = 0; i < items.length; i++) {
            b = items[i][1]; dx = 0; dy = 0;
            if (mode === "left") { dx = -b.x; } else if (mode === "right") { dx = c.width - (b.x + b.w); } else if (mode === "hcenter") { dx = c.width / 2 - (b.x + b.w / 2); }
            else if (mode === "top") { dy = -b.y; } else if (mode === "bottom") { dy = c.height - (b.y + b.h); } else if (mode === "vcenter") { dy = c.height / 2 - (b.y + b.h / 2); }
            setAt(items[i][0].transform.position, c.time, moved(b.P, dx, dy));
        }
        return "Aligned " + items.length + " layer(s) " + mode;
    }

    // ------------------------------------------------------------ AI tab
    function captions() {
        var c = comp(), l = layers()[0], tl = clipOf(l, c), mov = null, i;
        tl.audio = tl.video;
        say("Transcribing and rendering captions…");
        var res = http("POST", "/run", { feature: "captions", timeline: tl, params: { output: "overlay" } });
        for (i = 0; i < res.files.length; i++) { if (/\.mov$/i.test(res.files[i])) { mov = res.files[i]; } }
        if (!mov) { return "No speech found"; }
        importAbove(mov, l, 0).name = "Kerf captions";
        return "Captions added (" + res.report.captions + " lines)";
    }
    function openPanel() {  // the full Kerf UI lives in the docked panel, not in a browser
        return "All AI features: open Window > Extensions > Kerf";
    }

    // ------------------------------------------------------------ live: tell Kerf which project / comp / time is open
    var live;
    function startStudio() {  // start the Kerf helper (it runs the engine) when the engine isn't running
        var win = $.os.indexOf("Windows") >= 0;
        var h = locator().helper, f = h ? (win ? new File(h) : new Folder(h)) :
            win ? new File($.getenv("LOCALAPPDATA") + "/Kerf/kerf.exe") : new Folder("/Applications/Kerf.app");
        if (!f.exists) { return false; }
        if (win) { return f.execute(); }  // no cmd in between: nothing flashes on screen
        system.callSystem('open -g "' + f.fsName + '"');
        return true;
    }
    function liveState() {
        var c = app.project.activeItem, st = { project: app.project.file ? app.project.file.displayName : "Untitled project" };
        if (c instanceof CompItem) {
            st.sequence = c.name; st.playhead = c.time; st.fps = c.frameRate; st.width = c.width; st.height = c.height;
            st.timecode = timeToCurrentFormat(c.time, c.frameRate);
        }
        return st;
    }
    $.global.kerfBeat = function () {
        try {
            var st = liveState();
            http("POST", "/host/heartbeat", { host: "aftereffects", state: st }, 2);
            if (live) { live.text = st.project + (st.sequence ? ", " + st.sequence + ", " + st.timecode : ""); }
        } catch (e) { try { if (live) { live.text = "Kerf engine not running"; } } catch (e2) { /* panel closed */ } }
    };

    // ------------------------------------------------------------ UI
    function btn(parent, label, fn, help) { var b = parent.add("button", undefined, label); b.onClick = fn; if (help) { b.helpTip = help; } return b; }
    function group(parent, title, orient) {
        var p = parent.add("panel", undefined, title); p.orientation = orient || "row"; p.alignChildren = ["fill", "top"]; p.margins = 10; p.spacing = 6;
        return p;
    }
    function sliderRow(parent, label, key, min, max) {
        var g = parent.add("group"); g.add("statictext", undefined, label).preferredSize.width = 90;
        var s = g.add("slider", undefined, S[key], min, max); s.preferredSize.width = 150;
        var v = g.add("statictext", undefined, String(S[key])); v.preferredSize.width = 40;
        s.onChanging = function () { S[key] = Math.round(s.value * 100) / 100; v.text = String(S[key]); };
    }
    function each(list, fn) { var i; for (i = 0; i < list.length; i++) { fn(list[i]); } }

    function build(thisObj) {
        var win = thisObj instanceof Panel ? thisObj : new Window("palette", "Kerf", undefined, { resizeable: true });
        win.orientation = "column"; win.alignChildren = ["fill", "top"]; win.margins = 8; win.spacing = 6;
        var mark = win.add("statictext", undefined, "kerf");  // the Kerf wordmark, as in the HTML panel
        try {
            mark.graphics.font = ScriptUI.newFont("Arial Black", "BOLDITALIC", 20);
            mark.graphics.foregroundColor = mark.graphics.newPen(mark.graphics.PenType.SOLID_COLOR, [1, 0.42, 0.17, 1], 1);
        } catch (e) { /* fonts and pens are optional: the plain label still reads */ }
        win.minimumSize = [280, 200];  // may be shorter than its content: the view scrolls
        // the tabs sit in a clipping view with a scrollbar, so a short docked panel can still reach everything
        var body = win.add("group"); body.orientation = "row"; body.alignment = ["fill", "fill"]; body.alignChildren = ["fill", "fill"]; body.spacing = 2;
        var view = body.add("group"); view.orientation = "column"; view.alignment = ["fill", "fill"]; view.alignChildren = ["fill", "top"]; view.margins = 0;
        view.minimumSize = [200, 80];
        var sb = body.add("scrollbar", undefined, 0, 0, 0); sb.alignment = ["right", "fill"]; sb.preferredSize.width = 14;
        var tabs = view.add("tabbedpanel"); tabs.alignChildren = ["fill", "top"];
        tabs.minimumSize = [200, 60];  // let the layout give the view less than the full height
        var tMain = tabs.add("tab", undefined, "Tools"), tGraphs = tabs.add("tab", undefined, "Graphs"), tMotion = tabs.add("tab", undefined, "Motion"),
            tShakes = tabs.add("tab", undefined, "Shakes"), tAI = tabs.add("tab", undefined, "Edit");

        // TOOLS
        var row = tMain.add("group"); row.alignChildren = ["fill", "top"];
        var pa = group(row, "Anchor", "column"), gr = null, n = 0;
        each([["↖", 0, 0], ["↑", .5, 0], ["↗", 1, 0], ["←", 0, .5], ["●", .5, .5], ["→", 1, .5], ["↙", 0, 1], ["↓", .5, 1], ["↘", 1, 1]], function (g) {
            if (n++ % 3 === 0) { gr = pa.add("group"); gr.spacing = 2; }
            btn(gr, g[0], act("Anchor", function () { return anchor(g[1], g[2]); })).preferredSize = [30, 26];
        });
        var pl = group(row, "Add layer", "column");
        btn(pl, "Null", act("Null", function () { return addNull(false); }));
        btn(pl, "Null + parent", act("Null + parent", function () { return addNull(true); }), "Parents the selected layers to a new null");
        btn(pl, "Adjustment", act("Adjustment", function () { return addSolid(true); }));
        btn(pl, "Solid…", act("Solid", function () { return addSolid(false); }));
        var pb = group(row, "Beats", "column");
        btn(pb, "Place beats", act("Beats", placeBeats), "Select the music layer");
        btn(pb, "Clear", act("Clear beats", clearBeats));
        var ev = pb.add("dropdownlist", undefined, ["Every beat", "Every 2", "Every 4 (bar)", "Every 8"]); ev.selection = 0;
        ev.onChange = function () { S.every = [1, 2, 4, 8][ev.selection.index]; };

        var row2 = tMain.add("group"); row2.alignChildren = ["fill", "top"];
        btn(group(row2, "Stabilizer"), "Stabilize", act("Stabilize", stabilize), "Pre-comps each layer and adds Warp Stabilizer");
        var pz = group(row2, "Zoom", "column");
        each(["in", "out"], function (dir) {
            var z = pz.add("group"); z.add("statictext", undefined, dir === "in" ? "Zoom in" : "Zoom out");
            each(["in", "out"], function (side) { btn(z, "ease " + side, act("Zoom " + dir, function () { return zoom(dir, side); })); });
        });
        btn(tMain, "Quick mask: draw a mask, then click", act("Quick mask", quickMask), "Draw a rectangle mask on the footage layer to limit the region (optional)");
        var pu = group(tMain, "Utilities");
        btn(pu, "Save frame to Desktop", act("Frame export", frameExport)); btn(pu, "Sort project", act("Sort project", sortProject));
        var pf = group(tMain, "FX presets");
        var fxName = pf.add("edittext", undefined, "My look"); fxName.preferredSize.width = 110;
        btn(pf, "Copy FX", act("Copy FX", function () { return copyFx(fxName.text); }));
        var fxList = pf.add("dropdownlist", undefined, []); fxList.preferredSize.width = 120;
        btn(pf, "Refresh", function () {
            try { var r = http("GET", "/fx"); fxList.removeAll(); each(r.presets, function (p) { fxList.add("item", p); }); say(r.presets.length + " presets"); } catch (e) { say(e.message); }
        });
        btn(pf, "Apply FX", act("Apply FX", function () { return fxList.selection ? applyFx(fxList.selection.text) : "Pick a preset (Refresh lists them)"; }));

        // GRAPHS
        var pv = group(tGraphs, "Value (selected keyframes)");
        each(["Ease out", "Ease in", "Ease in/out", "Snappy", "Linear"], function (nm) { btn(pv, nm, act("Value curve", function () { return valueCurve(nm); })); });
        var pspd = group(tGraphs, "Speed (time remap on selected layers)");
        each([["Ease in", "ease_in"], ["Ease out", "ease_out"], ["Speedramp", "speedramp"], ["Ease in/out", "ease_in_out"], ["Linear", "linear"]], function (k) {
            btn(pspd, k[0], act("Speed curve", function () { return speedCurve(k[1]); }));
        });

        // MOTION
        var pal = group(tMotion, "Align to comp");
        each([["Left", "left"], ["H centre", "hcenter"], ["Right", "right"], ["Top", "top"], ["V centre", "vcenter"], ["Bottom", "bottom"]], function (a) {
            btn(pal, a[0], act("Align", function () { return align(a[1]); }));
        });
        var pdi = group(tMotion, "Distribute");
        btn(pdi, "Horizontal", act("Distribute", function () { return align("dist_h"); })); btn(pdi, "Vertical", act("Distribute", function () { return align("dist_v"); }));
        var pzs = group(tMotion, "Zoom settings", "column");
        sliderRow(pzs, "Amount %", "amount", 101, 200); sliderRow(pzs, "Duration s", "zdur", 0.1, 5);

        // SHAKES
        var pax = group(tShakes, "Axis");
        each([["Vertical", "vertical"], ["Horizontal", "horizontal"], ["HV", "hv"], ["Scale", "scale"], ["All", "all"], ["Custom", "custom"]], function (a) {
            var r = pax.add("radiobutton", undefined, a[0]); r.value = a[1] === S.axis; r.onClick = function () { S.axis = a[1]; };
        });
        var psl = group(tShakes, "Settings", "column");
        sliderRow(psl, "Amplitude px", "amp", 0, 150); sliderRow(psl, "Frequency Hz", "freq", 1, 30); sliderRow(psl, "Rotation °", "rot", 0, 15);
        sliderRow(psl, "Duration s", "dur", 0.1, 5); sliderRow(psl, "Decay", "decay", 0, 1);
        var fl = psl.add("checkbox", undefined, "Flash on hit"); fl.onClick = function () { S.flash = fl.value; };
        btn(tShakes, "Apply shake at the playhead", act("Shake", shake));

        // AI
        var pai = group(tAI, "Kerf engine", "column");
        btn(pai, "Captions for the layer", act("Captions", captions));
        btn(pai, "All AI features (Kerf panel)", act("Kerf panel", openPanel));
        btn(pai, "Check engine", function () { try { http("GET", "/settings"); say("Engine OK"); } catch (e) { say(e.message); } });

        status = win.add("statictext", undefined, "Ready", { truncate: "end" });
        live = win.add("statictext", undefined, "", { truncate: "end" });
        tabs.selection = tMain;
        win.layout.layout(true);
        var flow = [row, row2];  // side-by-side groups stack when the docked panel is narrow
        function scroll() {  // the layout can't clip, so the scroll area is placed by hand after each resize
            var m = win.margins, w = win.size[0] - m[0] - m[2], foot = status.size[1] + live.size[1] + 2 * win.spacing;
            var top = m[1] + mark.size[1] + win.spacing;  // below the wordmark
            var h = Math.max(60, win.size[1] - top - m[3] - foot), over = Math.max(0, fullH - h), sw = over > 0 ? 16 : 0;
            mark.location = [m[0], m[1]];
            body.location = [m[0], top]; body.size = [w, h];
            view.location = [0, 0]; view.size = [w - sw, h];
            sb.visible = over > 0; sb.location = [w - 14, 0]; sb.size = [14, h];
            sb.maxvalue = over; if (sb.value > over) { sb.value = over; }
            tabs.size = [w - sw, Math.max(fullH, h)]; tabs.location = [0, -sb.value];
            status.location = [m[0], top + h + win.spacing]; status.size = [w, status.size[1]];
            live.location = [m[0], status.location[1] + status.size[1] + win.spacing]; live.size = [w, live.size[1]];
        }
        var laidOut = false, fullH = 0;  // fullH: the tabs' natural height, measured after a full layout
        function adapt() {  // full re-layout only when the stacking changes: it would snap the window to its content
            var narrow = win.size && win.size.width < 470, changed = !laidOut, keep = win.size ? [win.size[0], win.size[1]] : null;
            each(flow, function (r) { var o = narrow ? "column" : "row"; if (r.orientation !== o) { r.orientation = o; changed = true; } });
            if (changed) { win.layout.layout(true); laidOut = true; fullH = tabs.size[1]; if (keep && keep[0] > 0) { win.size = keep; } }
            win.layout.resize();
            scroll();
        }
        sb.onChanging = sb.onChange = function () { tabs.location = [0, -sb.value]; };
        tabs.onChange = function () { sb.value = 0; laidOut = false; adapt(); };
        win.onResizing = win.onResize = adapt;
        adapt();
        if (win instanceof Window) { win.center(); win.show(); }
    }
    if ($.global.KERF_LIB) {  // loaded by the HTML panel (aftereffects/cep): expose the tools, no ScriptUI
        var FUNCS = { anchor: anchor, "null": function () { return addNull(false); }, parentNull: function () { return addNull(true); },
            adjustment: function () { return addSolid(true); }, solid: function (hex) { return addSolid(false, hex); },
            clearBeats: clearBeats, stabilize: stabilize, zoom: zoom, frameExport: frameExport,
            sortProject: sortProject, copyFx: copyFx, applyFx: applyFx, valueCurve: valueCurve, speedCurve: speedCurve, shake: shake,
            align: align, clipInfo: clipInfo, addMarkers: addMarkers, addLayer: addLayer,
            importFiles: importFiles, placeFile: placeFile, compMarkers: compMarkers,
            listScripts: listScripts, runScript: runScript };
        $.global.KerfAE = {
            call: function (name, settings, args) {  // settings: the panel's values for S; returns JSON {ok, text}
                var k, r;
                for (k in settings) { if (settings.hasOwnProperty(k)) { S[k] = settings[k]; } }
                app.beginUndoGroup("Kerf: " + name);
                try { r = { ok: true, text: String(FUNCS[name].apply(null, args || []) || name + " done") }; }
                catch (e) { r = { ok: false, text: e.message }; }
                app.endUndoGroup();
                return json(r);
            },
            live: function () { try { return json(liveState()); } catch (e) { return "{}"; } },
            token: function () { try { return token(); } catch (e) { return ""; } },
            locate: function () { return json(locator()); },
            launch: function () { return startStudio() ? "1" : ""; }
        };
        return;
    }
    build(thisObj);
    try { http("GET", "/settings", undefined, 2); } catch (e) { if (startStudio()) { say("Starting Kerf\u2026"); } }
    if ($.global.kerfBeatTask) { app.cancelTask($.global.kerfBeatTask); $.global.kerfBeatTask = 0; }
    kerfBeat();  // once on open; no repeating socket task (idle-task sockets can destabilise AE)
})(this);
