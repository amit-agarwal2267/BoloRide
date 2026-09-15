import type { ReactNode } from "react";

// Original vector compositions; no platform artwork or icon-font dependency.
const drawings: Record<string, ReactNode> = {
  bubble: <><path d="M11 13h26v19H23l-8 6v-6h-4z" fill="white" stroke="none" rx="5"/><path d="M17 21h14M17 26h9" stroke="#46b97b"/></>,
  camera: <><path d="M10 17h8l3-4h8l3 4h6v20H10z" fill="#313b46" stroke="none"/><circle cx="24" cy="27" r="8" fill="#aebdcc"/><circle cx="24" cy="27" r="5" fill="#293d59"/><circle cx="22" cy="25" r="2" fill="#7dcde8" stroke="none"/></>,
  flower: <>{["#fa677a", "#ffb650", "#f3dc66", "#64cfb5", "#729ded", "#b392e8"].map((color,i)=><path key={color} d="M24 23C7 19 14 3 24 10C34 3 41 19 24 23" fill={color} stroke="none" transform={`rotate(${i*60} 24 24) scale(.75) translate(8 8)`}/>)}<circle cx="24" cy="24" r="4" fill="white" stroke="none"/></>,
  pin: <><path d="M4 33L44 13M15 0l12 48" stroke="#fff" strokeWidth="6"/><path d="M4 33L44 13" stroke="#eabe6b" strokeWidth="2"/><path d="M32 11a7 7 0 0 0-7 7c0 5 7 11 7 11s7-6 7-11a7 7 0 0 0-7-7" fill="#df615b" stroke="none"/><circle cx="32" cy="18" r="2" fill="white" stroke="none"/></>,
  sun: <><circle cx="18" cy="18" r="8" fill="#ffda78" stroke="none"/><path d="M13 35h24a6 6 0 0 0 0-12 9 9 0 0 0-17-2 7 7 0 0 0-7 14" fill="white" stroke="none"/></>,
  notes: <><path d="M12 10h24v29H12z" fill="#fff8dd" stroke="none"/><path d="M17 19h14M17 25h14M17 31h9" stroke="#b29960"/><path d="M12 13h24" stroke="#e9b44d" strokeWidth="5"/></>,
  clock: <><circle cx="24" cy="24" r="17" fill="#fff7e8" stroke="none"/><path d="M24 12v12l8 5" stroke="#303942"/><path d="M24 24l-5 9" stroke="#db735a"/><circle cx="24" cy="24" r="2" fill="#303942" stroke="none"/></>,
  gear: <><path d="M20 8h8l2 5 5 1 4 7-3 5 1 5-7 5-5-1-5 3-7-5v-6l-4-4 3-8 6-1z" fill="#dae1e4" stroke="none"/><circle cx="24" cy="23" r="8" fill="#66717d"/><circle cx="24" cy="23" r="4" fill="#b7c5ce" stroke="none"/></>,
  phone: <path d="M14 10l7 7-4 5c3 5 5 7 10 10l5-4 7 6c-3 9-10 7-20-2S6 14 14 10" fill="white" stroke="none"/>,
  music: <><path d="M22 32V14l14-3v18M22 19l14-3"/><ellipse cx="17" cy="33" rx="5" ry="4" fill="white" stroke="none"/><ellipse cx="31" cy="30" rx="5" ry="4" fill="white" stroke="none"/></>,
};
export function AppIcon({ kind }: { kind: string }) {
  return <i className={`app-icon app-art app-icon--${kind}`} aria-hidden="true"><svg viewBox="0 0 48 48" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{drawings[kind]}</svg></i>;
}
