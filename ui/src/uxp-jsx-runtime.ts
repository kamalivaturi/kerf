// JSX runtime for the Premiere (UXP) build only; vite.config.ts points jsxImportSource here in --mode uxp.
// UXP draws <button> as a native Spectrum control: it ignores Kerf's styling and hides children such as SVG icons.
// Every <button> becomes a <div role="button" class="kbtn"> with the same behaviour (click, Enter/Space, disabled),
// and the build maps the CSS `button` selectors to `.kbtn`, so the panel looks like Kerf Studio.
// UXP sliders also ignore `step` and report raw floats: their values are snapped before onChange sees them.
import * as R from "react/jsx-runtime";

export const Fragment = R.Fragment;

const cssVar = (v: unknown) => typeof v === "string" && v.includes("var(");

function adapt(type: any, props: any): [any, any] {
  if (props && (cssVar(props.stroke) || cssVar(props.fill))) {
    // UXP doesn't resolve var() in SVG attributes (the stroke disappears); it does in CSS
    const { stroke, fill, style, ...rest } = props;
    const css: Record<string, unknown> = { ...style };
    if (cssVar(stroke)) css.stroke = stroke; else if (stroke !== undefined) rest.stroke = stroke;
    if (cssVar(fill)) css.fill = fill; else if (fill !== undefined) rest.fill = fill;
    props = { ...rest, style: css };
  }
  if (type === "button") {
    const { disabled, onClick, onKeyDown, className, type: _kind, ...rest } = props || {};
    return ["div", {
      ...rest, role: "button", tabIndex: disabled ? -1 : 0, "aria-disabled": disabled ? "true" : undefined,
      className: className ? `kbtn ${className}` : "kbtn",
      onClick: disabled ? undefined : onClick,
      onKeyDown: (e: any) => {
        onKeyDown?.(e);
        if (!disabled && onClick && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onClick(e); }
      },
    }];
  }
  if (type === "input" && props?.type === "range" && props.onChange) {
    const step = Number(props.step) || 1, digits = (String(props.step ?? 1).split(".")[1] || "").length;
    const onChange = props.onChange;
    return [type, { ...props, onChange: (e: any) => {
      const v = Math.round(Number(e.target.value) / step) * step;
      e.target.value = v.toFixed(digits);
      onChange(e);
    } }];
  }
  return [type, props];
}

export function jsx(type: any, props: any, key?: any) { const [t, p] = adapt(type, props); return R.jsx(t, p, key); }
export function jsxs(type: any, props: any, key?: any) { const [t, p] = adapt(type, props); return R.jsxs(t, p, key); }
export const jsxDEV = jsx;
