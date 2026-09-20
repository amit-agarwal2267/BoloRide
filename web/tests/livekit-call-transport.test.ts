// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { FakeRoom, rooms, roomEvents } = vi.hoisted(() => {
  const roomEvents = {
    TrackSubscribed: "track-subscribed",
    TrackUnsubscribed: "track-unsubscribed",
    DataReceived: "data-received",
    Disconnected: "disconnected",
    ParticipantConnected: "participant-connected",
  };
  class FakeRoom {
    handlers = new Map<string, Set<(...args: unknown[]) => void>>();
    remoteParticipants = new Map();
    connect = vi.fn(async () => undefined);
    disconnect = vi.fn(async () => undefined);
    localParticipant = { setMicrophoneEnabled: vi.fn(async () => undefined) };
    constructor() { rooms.push(this); }
    on(event: string, handler: (...args: unknown[]) => void) {
      const handlers = this.handlers.get(event) ?? new Set();
      handlers.add(handler); this.handlers.set(event, handlers); return this;
    }
    once(event: string, handler: (...args: unknown[]) => void) {
      const once = (...args: unknown[]) => { this.off(event, once); handler(...args); };
      return this.on(event, once);
    }
    off(event: string, handler: (...args: unknown[]) => void) { this.handlers.get(event)?.delete(handler); return this; }
    emit(event: string, ...args: unknown[]) { this.handlers.get(event)?.forEach(handler => handler(...args)); }
  }
  const rooms: FakeRoom[] = [];
  return { FakeRoom, rooms, roomEvents };
});

vi.mock("livekit-client", () => ({
  Room: FakeRoom,
  RoomEvent: roomEvents,
  Track: { Kind: { Audio: "audio" } },
}));

import { LiveKitCallTransport } from "../lib/livekit-call-transport";

describe("LiveKitCallTransport", () => {
  beforeEach(() => {
    rooms.length = 0;
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({ serverUrl: "wss://livekit.test", participantToken: "test-token", callId: "call-123" }),
    })));
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.innerHTML = ""; });

  it("connects only through LiveKit, publishes the microphone, and plays agent audio", async () => {
    const transport = new LiveKitCallTransport();
    const connecting = transport.connect(new AbortController().signal);
    await vi.waitFor(() => expect(rooms).toHaveLength(1));
    const room = rooms[0];
    await vi.waitFor(() => expect(room.connect).toHaveBeenCalledWith("wss://livekit.test", "test-token"));
    room.emit(roomEvents.ParticipantConnected);
    await connecting;
    expect(room.localParticipant.setMicrophoneEnabled).toHaveBeenCalledWith(true);

    const element = document.createElement("audio");
    const track = { kind: "audio", attach: vi.fn(() => element), detach: vi.fn(() => [element]) };
    transport.setVolume(.4);
    room.emit(roomEvents.TrackSubscribed, track);
    expect(track.attach).toHaveBeenCalledOnce();
    expect(element.volume).toBe(.4);
    expect(document.body.contains(element)).toBe(true);
    await transport.setMuted(true);
    expect(room.localParticipant.setMicrophoneEnabled).toHaveBeenLastCalledWith(false);
    room.emit(roomEvents.TrackUnsubscribed, track);
    expect(document.body.contains(element)).toBe(false);
  });

  it("releases the leased caller number when the call disconnects", async () => {
    const transport = new LiveKitCallTransport();
    const connecting = transport.connect(new AbortController().signal);
    await vi.waitFor(() => expect(rooms).toHaveLength(1));
    const room = rooms[0];
    await vi.waitFor(() => expect(room.connect).toHaveBeenCalled());
    room.emit(roomEvents.ParticipantConnected);
    await connecting;

    await transport.disconnect();

    expect(fetch).toHaveBeenLastCalledWith(
      "/api/demo-phone",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ action: "end", call_id: "call-123" }),
      }),
    );
  });

  it("delivers only valid BoloRide backend notifications", async () => {
    const transport = new LiveKitCallTransport();
    const received = vi.fn();
    transport.setNotificationHandler(received);
    const connecting = transport.connect(new AbortController().signal);
    await vi.waitFor(() => expect(rooms).toHaveLength(1));
    const room = rooms[0];
    await vi.waitFor(() => expect(room.connect).toHaveBeenCalled());
    room.emit(roomEvents.ParticipantConnected);
    await connecting;
    const notification = { notification_id: "n1", type: "ride_booked", sender: "BR24IC42", ride_id: "r1", timestamp: "2026-09-14T00:00:00Z", payload: {} };
    const encode = (value: object) => new TextEncoder().encode(JSON.stringify(value));
    room.emit(roomEvents.DataReceived, encode(notification), undefined, undefined, "boloride.notifications");
    room.emit(roomEvents.DataReceived, encode({ ...notification, sender: "UNKNOWN" }), undefined, undefined, "boloride.notifications");
    room.emit(roomEvents.DataReceived, new Uint8Array([255]), undefined, undefined, "boloride.notifications");
    expect(received).toHaveBeenCalledOnce();
    expect(received).toHaveBeenCalledWith(notification);
  });
});
