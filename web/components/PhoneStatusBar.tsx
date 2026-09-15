"use client";
import { useClock } from "./PhoneClock";

export function PhoneStatusBar({ callActive = false, microphoneActive = false, onOpenControls }: {
  callActive?: boolean; microphoneActive?: boolean; onOpenControls?: () => void;
}) {
  const { time } = useClock();
  return <div className="phone-status-bar">
    <time data-testid="status-time">{time}</time>
    <span className="status-drawings" aria-label="Demo signal, Wi-Fi and battery">
      <svg viewBox="0 0 76 16" aria-hidden="true" fill="currentColor"><rect x="1" y="10" width="3" height="4" rx="1"/><rect x="6" y="7" width="3" height="7" rx="1"/><rect x="11" y="4" width="3" height="10" rx="1"/><rect x="16" y="1" width="3" height="13" rx="1"/><g fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"><path d="M26 5q8-7 16 0M29 8q5-4 10 0M32 11q2-2 4 0"/><rect x="49" y="3" width="22" height="11" rx="3"/></g><circle cx="34" cy="13" r="1"/><rect x="52" y="6" width="15" height="5" rx="1"/><path d="M73 6h2v5h-2z"/></svg>
    </span>
    {callActive && <><button className="status-open-controls" aria-label="Open Control Centre" onClick={onOpenControls}/><button className="active-call-indicator" onClick={onOpenControls} aria-label="BoloRide Call controls">BoloRide Call <span aria-hidden="true">⌄</span></button></>}
    {callActive && microphoneActive && <span className="privacy-led" role="status" aria-label="Call microphone active"/>}
  </div>;
}
