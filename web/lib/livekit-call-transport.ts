import { Room, RoomEvent, Track } from "livekit-client";
import type { CallTransport, RideNotification } from "./call-transport";

/** Real browser-to-LiveKit transport used by the interactive demo. */
export class LiveKitCallTransport implements CallTransport {
  private room: Room | undefined;
  private audio = new Set<HTMLMediaElement>();
  private volume = 1;
  private callId: string | undefined;
  private notificationHandler: ((notification: RideNotification) => void) | undefined;
  async connect(signal: AbortSignal): Promise<void> {
    const room = new Room({ adaptiveStream: true, dynacast: true });
    this.room = room;
    const abort = () => { void this.disconnect(); };
    signal.addEventListener("abort", abort, { once: true });
    const check = () => { if (signal.aborted || this.room !== room) throw new DOMException("Call cancelled", "AbortError"); };
    room.on(RoomEvent.TrackSubscribed, track => {
      if (track.kind !== Track.Kind.Audio || this.room !== room || signal.aborted) return;
      const element = track.attach(); element.volume = this.volume;
      this.audio.add(element); document.body.appendChild(element);
    });
    room.on(RoomEvent.TrackUnsubscribed, track => {
      track.detach().forEach(element => { this.audio.delete(element); element.remove(); });
    });
    room.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic !== "boloride.notifications" || this.room !== room) return;
      try {
        const value = JSON.parse(new TextDecoder().decode(payload)) as RideNotification;
        if (value.sender === "BR24IC42" && (value.type === "ride_booked" || value.type === "ride_cancelled")) {
          this.notificationHandler?.(value);
        }
      } catch { /* Ignore malformed, unauthenticated display data. */ }
    });
    room.on(RoomEvent.Disconnected, () => { signal.removeEventListener("abort", abort); this.clearAudio(); });
    try {
      check();
      const response = await fetch("/api/livekit-token", { method: "POST", signal });
      if (!response.ok) throw new Error("The voice demo is unavailable.");
      const { serverUrl, participantToken, callId } = await response.json(); this.callId = callId; check();
      await room.connect(serverUrl, participantToken); check();
      await room.localParticipant.setMicrophoneEnabled(true); check();
      if (!room.remoteParticipants.size) await new Promise<void>((resolve, reject) => {
        const cleanup = () => { clearTimeout(timer); room.off(RoomEvent.ParticipantConnected, joined); signal.removeEventListener("abort", cancelled); };
        const joined = () => { cleanup(); resolve(); };
        const cancelled = () => { cleanup(); reject(new DOMException("Call cancelled", "AbortError")); };
        const timer = setTimeout(() => { cleanup(); reject(new Error("BoloRide did not join the call.")); }, 20_000);
        room.once(RoomEvent.ParticipantConnected, joined);
        signal.addEventListener("abort", cancelled, { once: true });
        if (signal.aborted) cancelled();
      });
      check();
    } catch (error) { signal.removeEventListener("abort", abort); await this.disconnect(); throw error; }
  }
  private clearAudio() { this.audio.forEach(element => element.remove()); this.audio.clear(); }
  async disconnect() { const room = this.room; this.room = undefined; const callId = this.callId; this.callId = undefined; this.clearAudio(); await room?.disconnect(); if (callId) { await fetch("/api/demo-phone", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "end", call_id: callId }), keepalive: true }).catch(() => undefined); } }
  async setMuted(muted: boolean) { await this.room?.localParticipant.setMicrophoneEnabled(!muted); }
  setVolume(volume: number) { this.volume = volume; this.audio.forEach(element => { element.volume = volume; }); }
  setNotificationHandler(handler: (notification: RideNotification) => void) { this.notificationHandler = handler; }
}
