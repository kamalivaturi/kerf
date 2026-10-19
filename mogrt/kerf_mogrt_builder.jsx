// Kerf MOGRT builder for Adobe After Effects (2021+).
// Run by `python -m kerf mogrt build` (AfterFX.exe -r this file). Reads build/specs.json next to this file,
// builds one comp per template, exposes every visual property in Essential Graphics, saves the project,
// exports .mogrt files and writes build/result.json. All styling flows from the "Controls" layer, so every
// look and animation stays editable in Premiere's Essential Graphics panel.
(function () {
    var here = File($.fileName).parent;
    var specFile = new File(here.fsName + "/build/specs.json");
    specFile.encoding = "UTF-8";
    specFile.open("r");
    var cfg = eval("(" + specFile.read() + ")"); // our own generated file, not user content
    specFile.close();
    var out = new Folder(cfg.out);
    if (!out.exists) out.create();
    var logLines = [], results = [];
    function log(s) { logLines.push(s); }

    var EASE = {
        back: "function E(p){var s=1.70158;p=p-1;return p*p*((s+1)*p+s)+1;}",
        cubic: "function E(p){return 1-Math.pow(1-p,3);}",
        expo: "function E(p){return p>=1?1:1-Math.pow(2,-10*p);}",
        bounce: "function E(p){var n=7.5625,d=2.75;if(p<1/d)return n*p*p;if(p<2/d){p-=1.5/d;return n*p*p+.75;}if(p<2.5/d){p-=2.25/d;return n*p*p+.9375;}p-=2.625/d;return n*p*p+.984375;}",
        step: "function E(p){return p>0?1:0;}",
        linear: "function E(p){return p;}"
    };

    function ctlRef(name, sub) { return 'thisComp.layer("Controls").effect("' + name + '")("' + sub + '")'; }

    function addCtl(layer, matchName, name, value) {
        var e = layer.property("ADBE Effect Parade").addProperty(matchName);
        e.name = name;
        if (value !== undefined && value !== null) e.property(1).setValue(value);
        return e;
    }

    function expose(comp, prop, name) {
        if (prop.canAddToMotionGraphicsTemplate(comp)) prop.addToMotionGraphicsTemplateAs(comp, name);
        else log("  cannot expose " + name);
    }

    function hexToRgb(h) {
        h = h.replace("#", "");
        return [parseInt(h.substr(0, 2), 16) / 255, parseInt(h.substr(2, 2), 16) / 255, parseInt(h.substr(4, 2), 16) / 255];
    }

    function styleText(layer, look, size, justify) {
        var tp = layer.property("ADBE Text Properties").property("ADBE Text Document");
        var td = tp.value;
        td.resetCharStyle();
        td.font = look.font;
        td.fontSize = size;
        td.applyFill = true;
        td.fillColor = hexToRgb(look.fill);
        td.applyStroke = true;
        td.strokeColor = hexToRgb(look.stroke);
        td.strokeWidth = 1;
        td.strokeOverFill = false;
        td.justification = justify;
        if (look.tracking !== undefined) td.tracking = look.tracking;
        if (look.leading) { td.autoLeading = false; td.leading = look.leading; }
        if (look.kerning) { try { td.kerningType = look.kerning === "optical" ? KerningType.OPTICAL : KerningType.METRICS; } catch (ek) { log("  kerning not set: " + ek); } }
        tp.setValue(td);
        return tp;
    }

    // Animator whose amount is computed per word/char by an Expression Selector.
    function animator(layer, name, props, amountExpr, basedOn) {
        var a = layer.property("ADBE Text Properties").property("ADBE Text Animators").addProperty("ADBE Text Animator");
        a.name = name;
        var ap = a.property("ADBE Text Animator Properties");
        for (var i = 0; i < props.length; i++) {
            var p = ap.addProperty(props[i][0]);
            if (props[i][2]) p.expression = props[i][2]; else p.setValue(props[i][1]);
        }
        var sel = a.property("ADBE Text Selectors").addProperty("ADBE Text Expressible Selector");
        try { sel.property("ADBE Text Range Type2").setValue(basedOn); } catch (e1) { log("  basedOn not set: " + e1); }
        sel.property("ADBE Text Expressible Amount").expression = amountExpr;
        return a;
    }

    function introExpr(anim) {
        var spd = "var spd=Math.max(.05," + ctlRef("Animation Speed", "Slider") + "/100);";
        if (anim.ease === "flicker")
            return spd + "var t=(time-inPoint)*spd;seedRandom(textIndex,true);var on=t>random(0,.6)+(textIndex/textTotal)*.4;" +
                "var a=on?(t<1&&random()<.25?1:0):1;selectorValue*a";
        if (anim.ease === "wave")
            return spd + "selectorValue*Math.sin((time-inPoint)*6*spd-textIndex*.55)";
        return (EASE[anim.ease] || EASE.cubic) + spd +
            "var stg=" + ctlRef("Stagger (s)", "Slider") + "/spd;var dur=" + anim.dur + "/spd;" +
            "var p=clamp((time-inPoint-(textIndex-1)*stg)/dur,0,1);var a=1-E(p);" +
            "if(" + ctlRef("Animate Out", "Checkbox") + "==1&&p>=1){var q=clamp((time-(outPoint-dur-(textTotal-textIndex)*stg))/dur,0,1);a=Math.max(a,1-E(1-q));}" +
            "selectorValue*a";
    }

    function build(t) {
        var comp = app.project.items.addComp(t.name, t.w, t.h, 1, t.duration, 30);
        comp.motionGraphicsTemplateName = t.name;
        comp.workAreaStart = 0;
        comp.workAreaDuration = t.preview_seconds;
        var look = t.look;

        // ---- Controls (every editable value lives here) ----
        var ctl = comp.layers.addNull(t.duration);
        ctl.name = "Controls";
        var c = {};
        c.size = addCtl(ctl, "ADBE Slider Control", "Size %", 100);
        c.fill = addCtl(ctl, "ADBE Color Control", "Fill Color", hexToRgb(look.fill));
        c.stroke = addCtl(ctl, "ADBE Color Control", "Stroke Color", hexToRgb(look.stroke));
        c.strokeW = addCtl(ctl, "ADBE Slider Control", "Stroke Width", look.stroke_width);
        c.track = addCtl(ctl, "ADBE Slider Control", "Letter Spacing", 0);
        c.lead = addCtl(ctl, "ADBE Slider Control", "Line Spacing", 0);
        c.hl = addCtl(ctl, "ADBE Color Control", "Highlight Color", hexToRgb(look.highlight));
        c.hlOn = addCtl(ctl, "ADBE Checkbox Control", "Highlight Active Word", t.kind === "caption" && look.highlight_on ? 1 : 0);
        c.hlScale = addCtl(ctl, "ADBE Slider Control", "Highlight Scale %", 112);
        c.speed = addCtl(ctl, "ADBE Slider Control", "Animation Speed", 100);
        c.stagger = addCtl(ctl, "ADBE Slider Control", "Stagger (s)", t.anim.stagger);
        c.out = addCtl(ctl, "ADBE Checkbox Control", "Animate Out", 0);
        c.box = addCtl(ctl, "ADBE Checkbox Control", "Box", look.box ? 1 : 0);
        c.boxColor = addCtl(ctl, "ADBE Color Control", "Box Color", hexToRgb(look.box_color));
        c.boxOp = addCtl(ctl, "ADBE Slider Control", "Box Opacity", look.box_opacity);
        c.boxPad = addCtl(ctl, "ADBE Slider Control", "Box Padding", 28);
        c.boxRound = addCtl(ctl, "ADBE Slider Control", "Box Roundness", 16);
        c.shadow = addCtl(ctl, "ADBE Checkbox Control", "Shadow", look.shadow ? 1 : 0);
        c.shadowOp = addCtl(ctl, "ADBE Slider Control", "Shadow Opacity", 60);
        c.glow = addCtl(ctl, "ADBE Slider Control", "Glow Intensity", look.glow);
        c.pos = addCtl(ctl, "ADBE Point Control", "Position", [t.w * t.pos[0], t.h * t.pos[1]]);
        if (t.kind === "lower_third") c.accent = addCtl(ctl, "ADBE Color Control", "Accent Color", hexToRgb(look.highlight));

        // ---- Box behind the text ----
        var box = comp.layers.addShape();
        box.name = "Box";
        var grp = box.property("ADBE Root Vectors Group").addProperty("ADBE Vector Group");
        var rect = grp.property("ADBE Vectors Group").addProperty("ADBE Vector Shape - Rect");
        rect.property("ADBE Vector Rect Size").expression =
            'var L=thisComp.layer("Text");var r=L.sourceRectAtTime(time,false);var s=L.transform.scale[0]/100;var p=' +
            ctlRef("Box Padding", "Slider") + ';[r.width*s+2*p,r.height*s+2*p]';
        rect.property("ADBE Vector Rect Roundness").expression = ctlRef("Box Roundness", "Slider");
        var fill = grp.property("ADBE Vectors Group").addProperty("ADBE Vector Graphic - Fill");
        fill.property("ADBE Vector Fill Color").expression = ctlRef("Box Color", "Color");
        box.transform.position.expression = 'thisComp.layer("Text").transform.position';
        box.transform.opacity.expression = ctlRef("Box", "Checkbox") + "*" + ctlRef("Box Opacity", "Slider");

        // ---- Accent bar (lower thirds) ----
        if (t.kind === "lower_third") {
            var bar = comp.layers.addShape();
            bar.name = "Accent";
            var bg = bar.property("ADBE Root Vectors Group").addProperty("ADBE Vector Group");
            var br = bg.property("ADBE Vectors Group").addProperty("ADBE Vector Shape - Rect");
            br.property("ADBE Vector Rect Size").expression =
                'var L=thisComp.layer("Text");var r=L.sourceRectAtTime(time,false);var s=L.transform.scale[0]/100;[12,r.height*s*2.1]';
            var bf = bg.property("ADBE Vectors Group").addProperty("ADBE Vector Graphic - Fill");
            bf.property("ADBE Vector Fill Color").expression = ctlRef("Accent Color", "Color");
            bar.transform.position.expression =
                'var L=thisComp.layer("Text");var r=L.sourceRectAtTime(time,false);var s=L.transform.scale[0]/100;' +
                'L.transform.position+[-r.width*s/2-30,r.height*s*.55]';
        }

        // ---- Main text ----
        var ALIGN = { left: ParagraphJustification.LEFT_JUSTIFY, center: ParagraphJustification.CENTER_JUSTIFY, right: ParagraphJustification.RIGHT_JUSTIFY };
        var just = ALIGN[look.align || (t.kind === "lower_third" ? "left" : "center")];
        var txt = comp.layers.addText(t.text);
        txt.name = "Text";
        var tp = styleText(txt, look, t.size, just);
        txt.transform.anchorPoint.expression = 'var r=sourceRectAtTime(time,false);[r.left+r.width/2,r.top+r.height/2]';
        txt.transform.position.expression = ctlRef("Position", "Point");
        txt.transform.scale.expression = 'var s=' + ctlRef("Size %", "Slider") + ';[s,s]';
        animator(txt, "Style", [["ADBE Text Fill Color", null, ctlRef("Fill Color", "Color")],
            ["ADBE Text Stroke Color", null, ctlRef("Stroke Color", "Color")],
            ["ADBE Text Stroke Width", null, ctlRef("Stroke Width", "Slider")],
            ["ADBE Text Tracking Amount", null, ctlRef("Letter Spacing", "Slider")],
            ["ADBE Text Line Spacing", null, "[0," + ctlRef("Line Spacing", "Slider") + "]"]], "selectorValue", 1);
        animator(txt, "Highlight", [["ADBE Text Fill Color", null, ctlRef("Highlight Color", "Color")],
            ["ADBE Text Scale 3D", null, 'var s=' + ctlRef("Highlight Scale %", "Slider") + ';[s,s,100]']],
            'var n=Math.floor((time-inPoint)/Math.max(.01,(outPoint-inPoint)/textTotal))+1;' +
            'selectorValue*((' + ctlRef("Highlight Active Word", "Checkbox") + '==1&&n==textIndex)?1:0)', 3);
        var props = [];
        for (var k = 0; k < t.anim.props.length; k++) props.push([t.anim.props[k][0], t.anim.props[k][1], null]);
        animator(txt, "Animate", props, introExpr(t.anim), t.anim.based_on);

        var fx = txt.property("ADBE Effect Parade");
        var sh = fx.addProperty("ADBE Drop Shadow");
        sh.property("Opacity").expression = ctlRef("Shadow", "Checkbox") + "*" + ctlRef("Shadow Opacity", "Slider") + "*2.55";
        sh.property("Distance").setValue(6);
        sh.property("Softness").setValue(18);
        var glow = fx.addProperty("ADBE Glo2");
        glow.property("Glow Intensity").expression = ctlRef("Glow Intensity", "Slider") + "/25";
        glow.property("Glow Radius").setValue(28);

        // ---- Second line (lower thirds) ----
        if (t.kind === "lower_third") {
            var st = comp.layers.addText(t.subtext);
            st.name = "Subtitle";
            styleText(st, look, Math.round(t.size * 0.55), ParagraphJustification.LEFT_JUSTIFY);
            st.transform.anchorPoint.expression = 'var r=sourceRectAtTime(time,false);[r.left,r.top]';
            st.transform.position.expression =
                'var L=thisComp.layer("Text");var r=L.sourceRectAtTime(time,false);var s=L.transform.scale[0]/100;' +
                'L.transform.position+[-r.width*s/2,r.height*s*.65]';
            st.transform.scale.expression = 'var s=' + ctlRef("Size %", "Slider") + ';[s,s]';
            animator(st, "Animate", props, introExpr(t.anim), t.anim.based_on);
            expose(comp, st.property("ADBE Text Properties").property("ADBE Text Document"), "Subtitle");
        }

        // ---- Essential Graphics (order = panel order in Premiere) ----
        expose(comp, tp, "Text");
        var order = [["size", "Size %"], ["fill", "Fill Color"], ["stroke", "Stroke Color"], ["strokeW", "Stroke Width"],
            ["track", "Letter Spacing"], ["lead", "Line Spacing"],
            ["hl", "Highlight Color"], ["hlOn", "Highlight Active Word"], ["hlScale", "Highlight Scale %"],
            ["speed", "Animation Speed"], ["stagger", "Stagger (s)"], ["out", "Animate Out"], ["box", "Box"],
            ["boxColor", "Box Color"], ["boxOp", "Box Opacity"], ["boxPad", "Box Padding"], ["boxRound", "Box Roundness"],
            ["shadow", "Shadow"], ["shadowOp", "Shadow Opacity"], ["glow", "Glow Intensity"], ["pos", "Position"], ["accent", "Accent Color"]];
        for (var j = 0; j < order.length; j++) if (c[order[j][0]]) expose(comp, c[order[j][0]].property(1), order[j][1]);
        return comp;
    }

    // Never replace a project the user is working on: abort unless AE is idle (no saved file, no items).
    var userProject = app.project && (app.project.file !== null || app.project.numItems > 0);
    if (userProject) {
        var ab = new File(here.fsName + "/build/result.json");
        ab.encoding = "UTF-8";
        ab.open("w");
        ab.write('{"aep":"","templates":[],"log":["ABORT: After Effects has a project open (' +
            (app.project.file ? app.project.file.name.replace(/"/g, "'") : "unsaved") +
            '). Save and close it (or quit After Effects), then run the build again."]}');
        ab.close();
        return;
    }
    app.beginSuppressDialogs();
    try {
        app.newProject();
        var comps = [];
        for (var i = 0; i < cfg.templates.length; i++) {
            var t = cfg.templates[i];
            try { comps.push([t, build(t)]); log("built " + t.id); }
            catch (e) { log("FAILED build " + t.id + ": " + e.toString() + " line " + e.line); }
        }
        app.project.save(new File(out.fsName + "/kerf_mogrts.aep")); // export prompts unless saved first
        for (var n = 0; n < comps.length; n++) {
            var ok = false;
            try { ok = comps[n][1].exportAsMotionGraphicsTemplate(true, out.fsName); } catch (e2) { log("FAILED export " + comps[n][0].id + ": " + e2); }
            results.push('{"id":"' + comps[n][0].id + '","comp":"' + comps[n][1].name.replace(/"/g, '\\"') + '","exported":' + ok +
                ',"controls":' + comps[n][1].motionGraphicsTemplateControllerCount + "}");
            log((ok ? "exported " : "NOT exported ") + comps[n][0].id);
        }
    } catch (fatal) {
        log("FATAL " + fatal.toString() + " line " + fatal.line);
    }
    app.endSuppressDialogs(false);
    var lines = [];
    for (var z = 0; z < logLines.length; z++) lines.push('"' + logLines[z].replace(/\\/g, "/").replace(/"/g, "'") + '"');
    var res = new File(here.fsName + "/build/result.json");
    res.encoding = "UTF-8";
    res.open("w");
    res.write('{"aep":"' + (out.fsName + "/kerf_mogrts.aep").replace(/\\/g, "/") + '","templates":[' + results.join(",") +
        '],"log":[' + lines.join(",") + "]}");
    res.close();
    if (cfg.quit) app.quit();
})();
