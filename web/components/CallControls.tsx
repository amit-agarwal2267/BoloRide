"use client";

import { useEffect, useRef, useState } from "react";

import { useVerticalSwipe } from "../lib/use-vertical-swipe";

export function CallControls({ volume, onVolume, muted, onMute, onClose }: {
  volume: number; onVolume: (volume: number) => void; muted: boolean; onMute: () => void; onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [closing, setClosing] = useState(false);
  const [brightness, setBrightness] = useState(.8);
  const close = () => setClosing(true);
  const swipe = useVerticalSwipe({ direction: "up", onComplete: close, ignoreControls: true, threshold: 58 });
  useEffect(() => {
    if (!closing) return;
    const timer = setTimeout(onClose, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 180);
    return () => clearTimeout(timer);
  }, [closing, onClose]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => previous?.focus();
  }, []);
  return <div className={`control-backdrop ${closing ? "control-backdrop--closing" : ""}`} {...swipe.handlers} style={{ "--control-drag": `${swipe.offset * .45}px` } as React.CSSProperties} onClick={(event) => { if (event.target === event.currentTarget) close(); }}>
    <div ref={panel} className="control-centre" style={{ backgroundColor: `rgba(255,255,255,${brightness * .06})` }} role="dialog" aria-modal="true" aria-label="Control Centre"
      onKeyDown={(event) => {
        if (event.key === "Escape") { event.stopPropagation(); close(); }
        if (event.key === "Tab") {
          const nodes = panel.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input");
          if (!nodes?.length) return;
          const first = nodes[0], last = nodes[nodes.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      }}>
      <header className="control-handle"><span>Control Centre</span><button onClick={close} aria-label="Close Control Centre">×</button></header>
      <div className="control-call-pill">BoloRide Call <span>Connected</span></div>
      <div className="control-grid">
        <div className="control-tile connectivity" aria-label="Decorative connectivity indicators"><span>✈</span><span>◉</span><span>ᛒ</span><small>Connectivity · demo</small></div>
        <div className="control-tile media-tile"><span>♫</span><strong>Not Playing</strong><small>Media</small></div>
        <div className="control-tile system-tile" aria-label="Decorative orientation indicator">↻<small>Orientation</small></div>
        <div className="control-tile system-tile" aria-label="Decorative focus indicator">☾<small>Focus</small></div>
        <label className="control-tile brightness-tile"><span>☀</span><input aria-label="Demo brightness" type="range" min=".2" max="1" step=".01" value={brightness} onChange={event => setBrightness(Number(event.target.value))}/><small>Display · visual only</small></label>
        <label className="control-tile volume-tile">Playback volume<input aria-label="Remote playback volume" type="range" min="0" max="1" step="0.01" value={volume} onChange={(event) => onVolume(Number(event.target.value))}/><output>{Math.round(volume*100)}%</output></label>
      </div>
      <button className="control-mute" onClick={onMute} aria-pressed={muted}>{muted ? "Unmute microphone" : "Mute microphone"}</button>
      <div className="control-utilities" aria-label="Decorative utilities"><span>⌁<small>Light</small></span><span>◷<small>Timer</small></span><span>＋<small>Calculator</small></span><span>▣<small>Camera</small></span></div>
      <p className="control-footnote">Simulated call controls</p>
    </div>
  </div>;
}
