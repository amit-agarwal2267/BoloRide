"use client";

import Link from "next/link";
import type { CallTransport, RideNotification } from "../lib/call-transport";
import { SimulatedCallTransport } from "../lib/call-transport";
import { LiveKitCallTransport } from "../lib/livekit-call-transport";
import { PhoneClock, useClock } from "./PhoneClock";
import { useVerticalSwipe } from "../lib/use-vertical-swipe";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { AppIcon } from "./AppIcon";
import { CallControls } from "./CallControls";
import { PremiumPhone } from "./PremiumPhone";
import { DEMO_NUMBER, DISPLAY_DEMO_NUMBER, demoReducer, formatDemoNumber, initialDemoState, normalizeDialedNumber } from "../app/demo-state";
import { ArrowClockwise, Backspace, Camera, CaretLeft, ClockCounterClockwise, DotsNine, Flashlight, House, Microphone, MicrophoneSlash, PhoneCall, PhoneDisconnect, SpeakerHigh, SpeakerLow } from "@phosphor-icons/react";

const KEYS = [["1", ""], ["2", "ABC"], ["3", "DEF"], ["4", "GHI"], ["5", "JKL"], ["6", "MNO"], ["7", "PQRS"], ["8", "TUV"], ["9", "WXYZ"], ["*", ""], ["0", "+"], ["#", ""]] as const;
const APPS = [["Messages", "bubble"], ["Camera", "camera"], ["Photos", "flower"], ["Maps", "pin"], ["Weather", "sun"], ["Notes", "notes"], ["Clock", "clock"], ["Settings", "gear"]] as const;

type CallAttempt = {
  transport?: CallTransport;
  tune: HTMLAudioElement;
  abort: AbortController;
  connectionStarted: boolean;
  onTuneEnded: () => void;
  onTuneError: () => void;
};

function InPhoneDialog({ kind, onClose }: { kind: "app-error" | "incorrect-number"; onClose: () => void }) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    buttonRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); if (event.key === "Tab") { event.preventDefault(); buttonRef.current?.focus(); } };
    window.addEventListener("keydown", closeOnEscape);
    return () => { window.removeEventListener("keydown", closeOnEscape); previous?.focus(); };
  }, [onClose]);
  const incorrect = kind === "incorrect-number";
  return <div className="dialog-scrim"><div className="phone-dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title" aria-describedby="dialog-message"><h3 id="dialog-title">{incorrect ? "Incorrect number" : "Error"}</h3><p id="dialog-message">{incorrect ? "Please dial the BoloRide demo number." : "App not working"}</p><button ref={buttonRef} onClick={onClose}>OK</button></div></div>;
}

function LockScreen({ onUnlock }: { onUnlock: () => void }) {
  const { date, time } = useClock();
  const { offset, handlers } = useVerticalSwipe({ direction: "up", onComplete: onUnlock, startRange: [.2, 1], threshold: 68 });
  return <div className="phone-screen lock-screen" data-testid="lock-screen" {...handlers} style={{ "--unlock-offset": `${offset * .45}px`, "--unlock-opacity": Math.max(.4, 1 + offset / 320) } as React.CSSProperties}>
    <div className="lock-content"><p>{date}</p><time data-testid="lock-time">{time}</time><div className="lock-orbit" aria-hidden="true"><i /><i /><i /></div></div><div className="lock-actions" aria-hidden="true"><span><Flashlight weight="fill" /></span><span><Camera weight="bold" /></span></div><button className="unlock-control" onClick={onUnlock}><span aria-hidden="true">⌃</span> Swipe up to unlock</button>
  </div>;
}

function HomeScreen({ onPhone, onMessages, onUnavailable, unread }: { onPhone: () => void; onMessages: () => void; onUnavailable: () => void; unread: number }) {
  return <div className="phone-screen home-screen" data-testid="home-screen"><div className="app-grid">{APPS.map(([name, icon]) => <button key={name} onClick={name === "Messages" ? onMessages : onUnavailable} aria-label={`Open ${name}`}><span className="app-icon-wrap"><AppIcon kind={icon} />{name === "Messages" && unread > 0 && <b className="unread-badge">{unread}</b>}</span><small>{name}</small></button>)}</div><div className="dock"><button onClick={onPhone} aria-label="Open Phone"><AppIcon kind="phone" /><small>Phone</small></button><button onClick={onUnavailable} aria-label="Open Music"><AppIcon kind="music" /><small>Music</small></button></div></div>;
}

function messageBody(message: RideNotification) {
  const p = message.payload;
  return message.type === "ride_booked"
    ? `Your BoloRide is booked.\nRIDE ID: ${message.ride_id}\nSource: ${p.source}\nDestination: ${p.destination}\nEstimated Fare: ${p.estimated_fare}\nDriver Name: ${p.driver_name}\nVehicle Number: ${p.vehicle_number}\nETA: ${p.eta}`
    : `Your BoloRide has been cancelled successfully.\nRIDE ID: ${message.ride_id}\nSource: ${p.source}\nDestination: ${p.destination}\nBooking Time: ${p.booking_time}\nCancellation Time: ${p.cancellation_time}`;
}

function MessagesApp({ messages, thread, onHome, onThread }: { messages: RideNotification[]; thread: boolean; onHome: () => void; onThread: () => void }) {
  const latest = messages.at(-1);
  return <div className="phone-screen messages-app"><header><button onClick={thread ? onHome : onHome} aria-label="Back to home">‹</button><strong>{thread ? "BR24IC42" : "Messages"}</strong><span /></header>{thread ? <div className="message-thread">{messages.length ? messages.map(message => <div className="message-bubble" key={message.notification_id}>{messageBody(message).split("\n").map((line, index) => <span key={index}>{line}</span>)}</div>) : <p className="empty-messages">No messages yet.</p>}</div> : <div className="message-list"><h2>Messages</h2>{latest ? <button onClick={onThread}><span className="message-avatar">B</span><span><strong>BR24IC42</strong><small>{messageBody(latest).split("\n")[0]}</small></span><time>{new Date(latest.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time></button> : <p className="empty-messages">No messages yet.</p>}</div>}</div>;
}

type PhoneAppProps = {
  screen: "phone-recents" | "phone-keypad"; digits: string; onHome: () => void; onRecents: () => void; onKeypad: () => void;
  onDigit: (digit: string) => void; onDelete: () => void; onClear: () => void; onCall: () => void; onRecent: () => void;
};

function PhoneApp({ screen, digits, onHome, onRecents, onKeypad, onDigit, onDelete, onClear, onCall, onRecent }: PhoneAppProps) {
  useEffect(() => {
    if (screen !== "phone-keypad") return;
    const handler = (event: KeyboardEvent) => { if (document.querySelector('[role="dialog"]')) return; if (/^[0-9*#]$/.test(event.key)) onDigit(event.key); if (event.key === "Backspace") onDelete(); if (event.key === "Escape") onClear(); if (event.key === "Enter") onCall(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCall, onClear, onDelete, onDigit, screen]);
  return <div className="phone-screen phone-app"><header><button onClick={onHome} aria-label="Back to home"><CaretLeft weight="bold" /></button><strong>Phone</strong><span /></header>
    {screen === "phone-recents" ? <div className="recents-view"><h2>Recents</h2><p>Tap a contact to call</p><div className="recent-list"><button className="recent recent--boloride" onClick={onRecent}><span className="recent-avatar">B</span><span><strong>BoloRide</strong><small>{DISPLAY_DEMO_NUMBER}</small></span><time>now</time></button><button className="recent" type="button" disabled><span className="recent-avatar recent-avatar--muted">N</span><span><strong>Neighbourhood Café</strong><small>0000-100-2000</small></span><time>Fri</time></button><button className="recent" type="button" disabled><span className="recent-avatar recent-avatar--muted">H</span><span><strong>Home Services</strong><small>0000-300-4000</small></span><time>Wed</time></button></div></div> : <div className="keypad-view"><div className="dialed-number" aria-live="polite">{formatDemoNumber(digits) || <span>Enter number</span>}</div><button className="clear-number" onClick={onClear} disabled={!digits}>Clear</button><div className="keypad">{KEYS.map(([digit, letters]) => <button key={digit} onClick={() => onDigit(digit)} aria-label={`Dial ${digit}`}><strong>{digit}</strong><small>{letters}</small></button>)}</div><div className="keypad-actions"><span /><button className="call-button" onClick={onCall} aria-label="Call entered number"><PhoneCall weight="fill" /></button><button onClick={onDelete} disabled={!digits} aria-label="Delete digit" className="delete-button"><Backspace weight="bold" /></button></div></div>}
    <nav className="phone-tabs" aria-label="Phone views"><button className={screen === "phone-recents" ? "active" : ""} onClick={onRecents}><ClockCounterClockwise weight="bold" />Recents</button><button className={screen === "phone-keypad" ? "active" : ""} onClick={onKeypad}><DotsNine weight="bold" />Keypad</button></nav>
  </div>;
}

type CallScreenProps = { state: "calling-tune" | "connecting" | "connected" | "call-ended" | "call-error"; seconds: number; muted: boolean; micStatus: string; error: string; onMute: () => void; onEnd: () => void; onRetry: () => void; onHome: () => void; volume: number; onSpeaker: () => void };

function CallScreen({ state, seconds, muted, micStatus, error, onMute, onEnd, onRetry, onHome, volume, onSpeaker }: CallScreenProps) {
  const time = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  const [keypad, setKeypad] = useState(false);
  const [callDigits, setCallDigits] = useState("");
  const active = state === "calling-tune" || state === "connecting" || state === "connected";
  const status = state === "calling-tune" ? "Calling…" : state === "connecting" ? "Connecting…" : state === "connected" ? time : state === "call-ended" ? "Call Ended" : "Unable to connect";
  return <div className={`phone-screen call-screen call-screen--${state}`}><div className={`voice-orb ${state === "connected" ? "voice-orb--connected" : ""}`}><span>B</span><i /><i /></div><h2>BoloRide</h2><p className="call-number">{DISPLAY_DEMO_NUMBER}</p><strong className="call-state">{status}</strong>{state === "connected" && <p className="assistant-label"><i /> Voice ride assistant</p>}{active && <small className="mic-state">{micStatus}</small>}{state === "call-error" && <p className="call-error">{error}</p>}{active && <div className="call-wave" aria-hidden="true">{Array.from({ length: 9 }, (_, index) => <i key={index} />)}</div>}{keypad && state === "connected" && <div className="call-keypad"><output aria-label="In-call digits">{callDigits || "Keypad"}</output><small>Local keypad · tones are not sent</small><div className="keypad">{KEYS.map(([digit]) => <button key={digit} aria-label={`In-call ${digit}`} onClick={() => setCallDigits(value => (value + digit).slice(-20))}>{digit}</button>)}</div><button onClick={() => setKeypad(false)}>Close keypad</button></div>}<div className="call-controls">{state === "connected" && <button onClick={onMute} aria-pressed={muted}><i className="mute-icon" aria-hidden="true">{muted ? <MicrophoneSlash weight="fill" /> : <Microphone weight="fill" />}</i><span>{muted ? "Unmute" : "Mute"}</span></button>}{state === "connected" && <><button onClick={onSpeaker} aria-label="Speaker" aria-pressed={volume === 1} title="Browser playback volume: full or half"><i className="speaker-icon">{volume === 1 ? <SpeakerHigh weight="fill" /> : <SpeakerLow weight="fill" />}</i><span>Speaker</span></button><button onClick={() => setKeypad(!keypad)} aria-expanded={keypad}><i><DotsNine weight="bold" /></i><span>Keypad</span></button></>}{active && <button className="end-call" onClick={onEnd}><i><PhoneDisconnect weight="fill" /></i><span>End Call</span></button>}{!active && <button className="retry-call" onClick={onRetry}><i><ArrowClockwise weight="bold" /></i><span>Call again</span></button>}{!active && <button className="back-home" onClick={onHome}><i><House weight="fill" /></i><span>Home</span></button>}</div></div>;
}


const simulatedTransport = () => new SimulatedCallTransport();
const liveTransport = () => new LiveKitCallTransport();

export default function PhoneDemo({ createTransport, live = false }: { createTransport?: () => CallTransport; live?: boolean }) {
  const factory = createTransport ?? (live ? liveTransport : simulatedTransport);
  return <PhoneClock><PhoneExperience createTransport={factory}/></PhoneClock>;
}

function PhoneExperience({ createTransport }: { createTransport: () => CallTransport }) {
  const [demo, dispatch] = useReducer(demoReducer, initialDemoState);
  const [muted, setMuted] = useState(false);
  const [microphoneListening, setMicrophoneListening] = useState(false);
  const [controlsOpen, setControlsOpen] = useState(false);
  const [remoteVolume, setRemoteVolume] = useState(1);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<RideNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const attemptRef = useRef<CallAttempt | null>(null);
  const stopTune = useCallback((attempt: CallAttempt) => {
    attempt.tune.removeEventListener("ended", attempt.onTuneEnded);
    attempt.tune.removeEventListener("error", attempt.onTuneError);
    attempt.tune.pause();
    try { attempt.tune.currentTime = 0; } catch { /* Media may not be loaded. */ }
  }, []);
  const dispose = useCallback(() => {
    const attempt = attemptRef.current; attemptRef.current = null;
    if (!attempt) return;
    stopTune(attempt); attempt.abort.abort();
    if (attempt.transport) void Promise.resolve(attempt.transport.disconnect()).catch(() => undefined);
  }, [stopTune]);
  useEffect(() => {
    const leave = () => dispose();
    window.addEventListener("pagehide", leave);
    return () => { window.removeEventListener("pagehide", leave); dispose(); };
  }, [dispose]);
  useEffect(() => {
    if (demo.screen !== "connected") return;
    const started = performance.now();
    const timer = setInterval(() => setSeconds(Math.floor((performance.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [demo.screen]);
  const endCall = () => { dispose(); setControlsOpen(false); setMicrophoneListening(false); dispatch({ type: "call-ended" }); };
  const connect = async (number = demo.digits) => {
    if (normalizeDialedNumber(number) !== DEMO_NUMBER) { dispatch({ type: "invalid-number" }); return; }
    dispose(); setControlsOpen(false); setMuted(false); setMicrophoneListening(false); setRemoteVolume(1); setSeconds(0); setError("");
    dispatch({ type: "start-call" });
    const tune = new Audio("/audio/boloride-caller-tune.mp3");
    tune.loop = false; tune.volume = .32; tune.currentTime = 0;
    const failTune = () => {
      const attempt = attemptRef.current;
      if (!attempt || attempt.tune !== tune || attempt.connectionStarted) return;
      dispose(); setError("Caller tune could not play. Please try again."); dispatch({ type: "call-error" });
    };
    const beginConnection = async () => {
      const attempt = attemptRef.current;
      if (!attempt || attempt.tune !== tune || attempt.connectionStarted || attempt.abort.signal.aborted) return;
      attempt.connectionStarted = true;
      stopTune(attempt); dispatch({ type: "tune-ended" });
      try {
        const transport = createTransport();
        attempt.transport = transport;
        transport.setNotificationHandler?.(notification => {
          setMessages(current => current.some(item => item.notification_id === notification.notification_id) ? current : [...current, notification]);
          setUnread(value => value + 1);
        });
        transport.setVolume(1);
        await transport.connect(attempt.abort.signal);
        if (attemptRef.current !== attempt) return;
        setMicrophoneListening(true); dispatch({ type: "connected" });
      } catch {
        if (attemptRef.current !== attempt) return;
        dispose(); setMicrophoneListening(false); setError("Please try your call again."); dispatch({ type: "call-error" });
      }
    };
    const attempt: CallAttempt = { tune, abort: new AbortController(), connectionStarted: false, onTuneEnded: () => void beginConnection(), onTuneError: failTune };
    attemptRef.current = attempt;
    tune.addEventListener("ended", attempt.onTuneEnded, { once: true });
    tune.addEventListener("error", attempt.onTuneError, { once: true });
    void tune.play().catch(failTune);
  };
  const toggleMute = async () => {
    const attempt = attemptRef.current; if (!attempt) return;
    const next = !muted;
    if (!attempt.transport) return;
    await attempt.transport.setMuted(next);
    if (attemptRef.current === attempt) setMuted(next);
  };
  // One volume state. Speaker chooses 100% / 50%; slider changes persist.
  const setPlaybackVolume = (value: number) => {
    setRemoteVolume(value); attemptRef.current?.transport?.setVolume(value);
  };
  const connected = demo.screen === "connected";
  const callScreens = ["calling-tune", "connecting", "connected", "call-ended", "call-error"];
  return <main className="demo-experience">
    <nav className="demo-nav"><Link href="/" onClick={dispose}><span className="demo-nav-mark">B</span><strong>BoloRide</strong></Link><span>LIVE VOICE LAB · 01</span><Link className="demo-back" href="/" onClick={dispose}>Back to story ↗</Link></nav>
    <div className="demo-content-layout">
    <aside className="demo-intro" aria-labelledby="demo-title">
      <p className="demo-kicker"><i /> INTERACTIVE CALL</p>
      <h1 id="demo-title">Don’t watch it.<br/><em>Call it.</em></h1>
      <p>This is a working browser call, placed inside a familiar phone. Unlock it, open Phone, and call BoloRide from Recents.</p>
      <ol>
        <li><span>01</span><div><strong>Unlock</strong><small>Swipe up or tap the cue</small></div></li>
        <li><span>02</span><div><strong>Open Phone</strong><small>BoloRide is in Recents</small></div></li>
        <li><span>03</span><div><strong>Speak naturally</strong><small>Allow microphone access</small></div></li>
      </ol>
      <p className="demo-language">Try: “Kal subah 8 baje station ke liye cab book kar do.”</p>
    </aside>
    <div className="demo-stage"><div className="phone-aura" aria-hidden="true"/>
      <PremiumPhone connected={connected} microphoneActive={connected && microphoneListening && !muted} controlsOpen={controlsOpen} onOpenControls={() => setControlsOpen(true)}>
        <div className={controlsOpen ? "screen-content screen-content--obscured" : "screen-content"} inert={controlsOpen || !!demo.dialog}>
          {demo.screen === "locked" && <LockScreen onUnlock={() => dispatch({ type: "unlock" })}/>}
          {demo.screen === "home" && <HomeScreen unread={unread} onMessages={() => dispatch({ type: "open-messages" })} onPhone={() => dispatch({ type: "open-phone" })} onUnavailable={() => dispatch({ type: "open-unavailable-app" })}/>} 
          {(demo.screen === "messages" || demo.screen === "message-thread") && <MessagesApp messages={messages} thread={demo.screen === "message-thread"} onHome={() => dispatch({ type: "home" })} onThread={() => { setUnread(0); dispatch({ type: "open-message-thread" }); }}/>} 
          {(demo.screen === "phone-recents" || demo.screen === "phone-keypad") && <PhoneApp screen={demo.screen} digits={demo.digits} onHome={() => dispatch({ type: "home" })} onRecents={() => dispatch({ type: "open-recents" })} onKeypad={() => dispatch({ type: "open-keypad" })} onDigit={digit => dispatch({ type: "append-digit", digit })} onDelete={() => dispatch({ type: "delete-digit" })} onClear={() => dispatch({ type: "clear-digits" })} onCall={() => void connect()} onRecent={() => { dispatch({ type: "select-boloride" }); void connect(DEMO_NUMBER); }}/>}
          {callScreens.includes(demo.screen) && <CallScreen key={demo.screen} state={demo.screen as CallScreenProps["state"]} volume={remoteVolume} onSpeaker={() => setPlaybackVolume(remoteVolume === 1 ? .5 : 1)} seconds={seconds} muted={muted} micStatus={connected ? muted ? "Microphone muted" : "Microphone active" : "Connecting your call…"} error={error} onMute={() => void toggleMute()} onEnd={endCall} onRetry={() => void connect(DEMO_NUMBER)} onHome={() => dispatch({ type: "home" })}/>} 
        </div>
        {connected && controlsOpen && <CallControls volume={remoteVolume} onVolume={setPlaybackVolume} muted={muted} onMute={() => void toggleMute()} onClose={() => setControlsOpen(false)}/>}
        {demo.dialog && <InPhoneDialog kind={demo.dialog} onClose={() => dispatch({ type: "close-dialog" })}/>}
      </PremiumPhone>
    </div>
    </div>
    <p className="simulation-notice">Experimental prototype · simulated fleet · microphone permission required</p>
  </main>;
}
