// First open of the Kerf panel: what is set up, three tools worth trying first, then out of the way for good.
import { useEffect, useState } from "react";
import { api } from "./api";
import { EDITOR_NAME, host } from "./host";

type Open = (view: "edit", feature: string) => void;

export default function Welcome({ engine, onOpen, onClose }: { engine: string; onOpen: Open; onClose: () => void }) {
  const [step, setStep] = useState(0), [pic, setPic] = useState("");
  const editor = EDITOR_NAME[host.name] || "your editor";
  // a real Kerf caption template, when the MOGRT pack is installed; no picture otherwise
  useEffect(() => { api.mediaUrl("caption-pop-bold-16x9", "tile").then(setPic).catch(() => {}); }, []);
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  const tool = (feature: string, label: string) =>
    <button className="ghost" onClick={() => { onOpen("edit", feature); onClose(); }}>{label}</button>;
  const screens = [
    { head: "Kerf is ready.", body: `Kerf works on the open sequence, right here in ${editor}. Where to find it in each editor:`,
      extra: <ul className="wl-checks">
        <li><span>Kerf engine</span><b className="ok">running, v{engine}</b></li>
        <li><span>Premiere Pro</span><b>Window › UXP Plugins › Kerf</b></li>
        <li><span>After Effects</span><b>Window › Extensions › Kerf</b></li>
        <li><span>DaVinci Resolve</span><b>Effects › OpenFX › Kerf FX</b></li></ul> },
    { head: "Cut the pauses.", body: "Silences finds the dead air in the voice track and cuts it into a new sequence.",
      extra: tool("silences", "Open Silences") },
    { head: "Captions, word by word.", body: "Kerf transcribes the voice, Indian languages included, and styles every word.",
      extra: <>{pic && <img className="wl-pic" src={pic} alt="A Kerf caption template" onError={() => setPic("")} />}
        {tool("captions", "Open Captions")}</> },
    { head: "Zooms that follow the voice.", body: "AutoZoom punches in on cuts and emphasis; Motion and Shakes add the rest.",
      extra: tool("zoom", "Open AutoZoom") },
    { head: "You’re set.", body: "Every tool works on a copy of your sequence and never changes your source files.", extra: null },
  ];
  const s = screens[step], last = step === screens.length - 1;

  return (
    <div className="welcome" role="dialog" aria-modal="true" aria-label="Welcome to Kerf">
      <div className="wl-steps" aria-hidden="true">{screens.map((_, i) => <i key={i} className={i <= step ? "on" : ""} />)}</div>
      <main className="wl-body fade" key={step}>
        <p className="wl-count">{step + 1} of {screens.length}</p>
        <h2>{s.head}</h2>
        <p className="wl-text">{s.body}</p>
        {s.extra}
      </main>
      <footer className="wl-nav">
        {step > 0 ? <button className="ghost" onClick={() => setStep(step - 1)}>Back</button>
          : <button className="ghost" onClick={onClose}>Skip</button>}
        <button className="primary" onClick={() => (last ? onClose() : setStep(step + 1))}>{last ? "Start editing" : "Next"}</button>
      </footer>
    </div>
  );
}
