// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Home from "../app/page";
import PhoneDemo from "../components/PhoneDemo";
import { PhoneClock, useClock } from "../components/PhoneClock";
import { SIMULATED_CONNECTION_MS, SimulatedCallTransport, type RideNotification } from "../lib/call-transport";

const roomConstructor = vi.hoisted(() => vi.fn());
vi.mock("livekit-client", () => ({ Room: roomConstructor, RoomEvent: {}, Track: {} }));

class MockAudio {
  static instances: MockAudio[] = [];
  static rejectPlay = false;
  loop = false; volume = 1; currentTime = 99;
  play = vi.fn(() => MockAudio.rejectPlay ? Promise.reject(Error("play failed")) : Promise.resolve()); pause = vi.fn();
  private listeners = new Map<string, Set<EventListener>>();
  constructor(public src: string) { MockAudio.instances.push(this); }
  addEventListener(type: string, listener: EventListener) {
    const listeners = this.listeners.get(type) ?? new Set<EventListener>();
    listeners.add(listener); this.listeners.set(type, listeners);
  }
  removeEventListener(type: string, listener: EventListener) { this.listeners.get(type)?.delete(listener); }
  emit(type: "ended" | "error") { this.listeners.get(type)?.forEach(listener => listener(new Event(type))); }
}
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));
const advance = async (ms: number) => { await act(async () => { vi.advanceTimersByTime(ms); }); };
function unlock() { click(/swipe up to unlock/i); }
function phone() { unlock(); click("Open Phone"); }
function call() { phone(); click(/BoloRide/); }
const finishTune = async () => { MockAudio.instances.at(-1)?.emit("ended"); await advance(0); };
function bounds(node: HTMLElement) {
  vi.spyOn(node, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, top: 0, left: 0, width: 350, height: 720, right: 350, bottom: 720, toJSON() {} });
}
function swipe(node: HTMLElement, x: number, y: number, dx: number, dy: number, cancel = false) {
  bounds(node);
  fireEvent.pointerDown(node, { pointerId: 1, clientX: x, clientY: y, button: 0 });
  fireEvent.pointerMove(node, { pointerId: 1, clientX: x+dx, clientY: y+dy });
  if (cancel) fireEvent.pointerCancel(node, { pointerId: 1 });
  else fireEvent.pointerUp(node, { pointerId: 1, clientX: x+dx, clientY: y+dy });
}

class NotificationTransport extends SimulatedCallTransport {
  handler?: (notification: RideNotification) => void;
  setNotificationHandler(handler: (notification: RideNotification) => void) { this.handler = handler; }
  emit(notification: RideNotification) { this.handler?.(notification); }
}

describe("simulated phone experience", () => {
  beforeEach(() => {
    vi.useFakeTimers(); vi.setSystemTime(new Date(2026, 8, 14, 14, 39, 57));
    MockAudio.instances = [];
    MockAudio.rejectPlay = false;
    vi.stubGlobal("Audio", MockAudio);
    vi.stubGlobal("fetch", vi.fn(() => { throw Error("Network must not be used"); }));
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn(() => { throw Error("Microphone must not be used"); }) } });
    window.matchMedia = vi.fn(() => ({ matches: false } as MediaQueryList));
    roomConstructor.mockClear();
  });
  afterEach(() => {
    cleanup();
    expect(fetch).not.toHaveBeenCalled();
    expect(roomConstructor).not.toHaveBeenCalled();
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  });

  it("starts with a distinct landing page and links into the dedicated demo route", () => {
    const view = render(<Home/>);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Book a ride");
    expect(screen.queryByTestId("lock-screen")).not.toBeInTheDocument();
    screen.getAllByRole("link", { name: /Try Live Demo/ }).forEach(link => expect(link).toHaveAttribute("href", "/demo"));
    view.unmount(); render(<PhoneDemo/>);
    expect(screen.getByTestId("lock-screen")).toBeInTheDocument();
  });
  it.each([[35, 230], [175, 450], [305, 665]])("unlocks from broad lower-screen point %i/%i", (x,y) => {
    render(<PhoneDemo/>); swipe(screen.getByTestId("lock-screen"), x,y,3,-85);
    expect(screen.getByTestId("home-screen")).toBeInTheDocument();
  });
  it("rejects horizontal, short and cancelled unlock gestures", () => {
    render(<PhoneDemo/>);
    const lock = screen.getByTestId("lock-screen");
    swipe(lock,100,400,180,-90); expect(lock).toBeInTheDocument();
    swipe(lock,100,400,0,-30); expect(lock).toBeInTheDocument();
    swipe(lock,100,400,0,-100,true); expect(lock).toBeInTheDocument();
  });
  it("supports keyboard unlock and a personal, unbranded home", async () => {
    vi.useRealTimers();
    render(<PhoneDemo/>);
    screen.getByRole("button", { name: /swipe up to unlock/i }).focus();
    await userEvent.setup().keyboard(" ");
    expect(screen.getByTestId("home-screen")).not.toHaveTextContent(/BoloRide|Your journey/);
  });
  it("all non-Phone apps show an accessible dialog and restore focus", () => {
    render(<PhoneDemo/>); unlock();
    for (const name of ["Camera","Photos","Maps","Weather","Notes","Clock","Settings","Music"]) {
      const button = screen.getByRole("button", { name: `Open ${name}` }); button.focus(); fireEvent.click(button);
      expect(screen.getByRole("dialog")).toHaveTextContent("ErrorApp not workingOK");
      click("OK"); expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(button).toHaveFocus();
    }
  });
  it("opens the backend-driven Messages inbox without manufacturing a message", () => {
    render(<PhoneDemo createTransport={() => new SimulatedCallTransport()}/>); unlock();
    click("Open Messages");
    expect(screen.getByRole("heading", { name: "Messages" })).toBeInTheDocument();
    expect(screen.getByText("No messages yet.")).toBeInTheDocument();
    expect(screen.queryByText(/Your BoloRide is booked/)).not.toBeInTheDocument();
  });
  it("shows booking and cancellation backend events in one unread Messages thread", async () => {
    const transport = new NotificationTransport();
    render(<PhoneDemo createTransport={() => transport}/>); call(); await finishTune();
    await advance(SIMULATED_CONNECTION_MS);
    const base = { sender: "BR24IC42" as const, ride_id: "ride-123", timestamp: "2026-09-14T14:00:00Z" };
    act(() => transport.emit({ notification_id: "n1", type: "ride_booked", ...base, payload: { source: "Home", destination: "Station", estimated_fare: "INR 200", driver_name: "Amit", vehicle_number: "RJ 20 AB 1234", eta: "5 min" } }));
    act(() => transport.emit({ notification_id: "n2", type: "ride_cancelled", ...base, timestamp: "2026-09-14T14:05:00Z", payload: { source: "Home", destination: "Station", booking_time: "2026-09-14T14:00:00Z", cancellation_time: "2026-09-14T14:05:00Z" } }));
    click("End Call"); click(/Home/);
    expect(screen.getByText("2")).toHaveClass("unread-badge");
    click("Open Messages"); click(/BR24IC42/);
    expect(screen.getByText(/Estimated Fare: INR 200/)).toBeInTheDocument();
    expect(screen.getByText(/cancelled successfully/)).toBeInTheDocument();
  });
  it("Phone opens Recents and all twelve keys plus keyboard/delete/clear work", () => {
    render(<PhoneDemo/>); phone();
    expect(screen.getByRole("button", { name: /BoloRide/ })).toHaveTextContent("1800-258-2334");
    click(/Keypad/);
    for (const digit of "123456789*0#") {
      click("Clear"); click(`Dial ${digit}`);
      expect(document.querySelector(".dialed-number")).toHaveTextContent(digit);
    }
    click("Clear");
    for (const key of "369") fireEvent.keyDown(window, { key });
    expect(document.querySelector(".dialed-number")).toHaveTextContent("369");
    click("Delete digit"); expect(document.querySelector(".dialed-number")).toHaveTextContent("36");
  });
  it("invalid numbers cannot start transport or caller tune", () => {
    const createTransport = vi.fn(() => new SimulatedCallTransport());
    render(<PhoneDemo createTransport={createTransport}/>); phone(); click(/Keypad/); click("Dial 3"); click("Call entered number");
    expect(screen.getByRole("dialog")).toHaveTextContent("Incorrect number");
    expect(createTransport).not.toHaveBeenCalled(); expect(MockAudio.instances).toHaveLength(0);
  });
  it("plays the complete tune once before constructing or starting transport", async () => {
    const createTransport = vi.fn(() => new SimulatedCallTransport());
    render(<PhoneDemo createTransport={createTransport}/>); call();
    const tune = MockAudio.instances[0];
    expect(tune.loop).toBe(false); expect(tune.currentTime).toBe(0);
    expect(tune.src).toBe("/audio/boloride-caller-tune.mp3");
    expect(tune.play).toHaveBeenCalledOnce();
    await advance(SIMULATED_CONNECTION_MS * 2);
    expect(screen.getByText("Calling…")).toBeInTheDocument();
    expect(createTransport).not.toHaveBeenCalled();
    expect(tune.pause).not.toHaveBeenCalled();
    await finishTune();
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
    expect(createTransport).toHaveBeenCalledOnce();
    tune.emit("ended");
    expect(createTransport).toHaveBeenCalledOnce();
    await advance(SIMULATED_CONNECTION_MS);
    expect(screen.getByText("Voice ride assistant")).toBeInTheDocument();
    expect(tune.pause).toHaveBeenCalled(); expect(tune.currentTime).toBe(0);
  });
  it.each(["end", "unmount", "pagehide"])("stops tune on %s and ignores delayed connection", async reason => {
    const view = render(<PhoneDemo/>); call(); const tune = MockAudio.instances[0];
    if (reason === "end") click("End Call");
    else if (reason === "unmount") view.unmount();
    else fireEvent(window,new Event("pagehide"));
    expect(tune.pause).toHaveBeenCalled(); expect(tune.currentTime).toBe(0);
    tune.emit("ended"); await advance(SIMULATED_CONNECTION_MS);
    expect(screen.queryByText("Voice ride assistant")).not.toBeInTheDocument();
  });
  it("resets retry and stale attempts cannot affect a fresh call", async () => {
    render(<PhoneDemo/>); call(); await advance(1000); click("End Call"); click(/Call again/);
    expect(MockAudio.instances).toHaveLength(2); expect(MockAudio.instances[1].currentTime).toBe(0);
    MockAudio.instances[0].emit("ended");
    await advance(4000); expect(screen.getByText("Calling…")).toBeInTheDocument();
    expect(MockAudio.instances[1].pause).not.toHaveBeenCalled();
    await finishTune(); await advance(SIMULATED_CONNECTION_MS); expect(screen.getByText("Voice ride assistant")).toBeInTheDocument();
  });
  it("fails without constructing transport when caller tune playback fails", async () => {
    const createTransport = vi.fn(() => new SimulatedCallTransport());
    render(<PhoneDemo createTransport={createTransport}/>); call();
    MockAudio.instances[0].emit("error"); await advance(0);
    expect(screen.getByText("Unable to connect")).toBeInTheDocument();
    expect(screen.getByText("Caller tune could not play. Please try again.")).toBeInTheDocument();
    expect(createTransport).not.toHaveBeenCalled();
  });
  it("does not connect when the browser rejects caller tune playback", async () => {
    const createTransport = vi.fn(() => new SimulatedCallTransport());
    MockAudio.rejectPlay = true;
    render(<PhoneDemo createTransport={createTransport}/>); call(); await advance(0);
    expect(screen.getByText("Caller tune could not play. Please try again.")).toBeInTheDocument();
    expect(createTransport).not.toHaveBeenCalled();
  });
  it("cleans up on transport error", async () => {
    const disconnect = vi.fn();
    render(<PhoneDemo createTransport={() => ({ connect: async () => { throw Error("failed"); }, disconnect, setMuted() {}, setVolume() {} })}/>);
    call(); await finishTune(); await advance(0);
    expect(screen.getByText("Unable to connect")).toBeInTheDocument();
    expect(MockAudio.instances[0].pause).toHaveBeenCalled(); expect(disconnect).toHaveBeenCalled();
    expect(screen.queryByLabelText("Call microphone active")).not.toBeInTheDocument();
  });
  it("shows privacy only while connected/unmuted, and keeps one coherent volume", async () => {
    render(<PhoneDemo/>); call(); await finishTune();
    expect(screen.queryByLabelText("Call microphone active")).not.toBeInTheDocument();
    await advance(SIMULATED_CONNECTION_MS);
    expect(screen.getByLabelText("Call microphone active")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Speaker" })).toHaveAttribute("aria-pressed","true");
    click("Speaker"); click("Open Control Centre");
    expect(screen.getByRole("slider", { name: "Remote playback volume" })).toHaveValue("0.5");
    fireEvent.change(screen.getByRole("slider", { name: "Remote playback volume" }), { target: { value: ".37" } });
    click("Mute microphone"); await advance(0);
    expect(screen.queryByLabelText("Call microphone active")).not.toBeInTheDocument();
    click("Close Control Centre"); await advance(200);
    click("Unmute"); await advance(0);
    expect(screen.getByLabelText("Call microphone active")).toBeInTheDocument();
    click("Speaker"); expect(screen.getByRole("button", { name: "Speaker" })).toHaveAttribute("aria-pressed","true");
    click("Open Control Centre");
    expect(screen.getByRole("slider", { name: "Remote playback volume" })).toHaveValue("1");
    fireEvent.keyDown(screen.getByRole("dialog"),{key:"Escape"}); await advance(200);
    click("End Call");
    expect(screen.queryByLabelText("Call microphone active")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Control Centre" })).not.toBeInTheDocument();
  });
  it.each([[175,25],[315,25],[175,85],[300,125]])("opens Control Centre from top region %i/%i while call continues", async (x,y) => {
    render(<PhoneDemo/>); call(); await finishTune(); await advance(SIMULATED_CONNECTION_MS);
    swipe(screen.getByTestId("phone-glass"),x,y,3,75);
    expect(screen.getByRole("dialog", { name: "Control Centre" })).toBeInTheDocument();
    expect(screen.getByText("Voice ride assistant")).toBeInTheDocument();
    expect(screen.getByLabelText("Call microphone active")).toBeInTheDocument();
    swipe(document.querySelector(".control-backdrop")!,100,400,0,-80);
    await advance(200); expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Voice ride assistant")).toBeInTheDocument();
  });
  it("does not open Control Centre when calling or dragging horizontally", async () => {
    render(<PhoneDemo/>); call(); swipe(screen.getByTestId("phone-glass"),100,50,0,80);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await finishTune(); await advance(SIMULATED_CONNECTION_MS);
    swipe(screen.getByTestId("phone-glass"),100,50,160,80);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("preserves a touch gesture when implicit child capture transfers to the screen", async () => {
    render(<PhoneDemo/>); call(); await finishTune(); await advance(SIMULATED_CONNECTION_MS);
    const glass = screen.getByTestId("phone-glass"); bounds(glass);
    const child = screen.getByRole("button", { name: "Open Control Centre" });
    fireEvent.pointerDown(child, { pointerId: 4, clientX: 300, clientY: 25, button: 0 });
    fireEvent.pointerMove(glass, { pointerId: 4, clientX: 300, clientY: 55 });
    fireEvent.lostPointerCapture(child, { pointerId: 4 });
    fireEvent.pointerMove(glass, { pointerId: 4, clientX: 300, clientY: 110 });
    fireEvent.pointerUp(glass, { pointerId: 4, clientX: 300, clientY: 110 });
    expect(screen.getByRole("dialog", { name: "Control Centre" })).toBeInTheDocument();
  });
  it("shared local clock updates at the minute boundary and persists across screens", async () => {
    render(<PhoneDemo/>);
    const expected = (date: Date) => new Intl.DateTimeFormat(undefined,{hour:"numeric",minute:"2-digit"}).format(date);
    expect(screen.getByTestId("lock-time").textContent).toBe(screen.getByTestId("status-time").textContent);
    await advance(3000);
    expect(screen.getByTestId("lock-time")).toHaveTextContent(expected(new Date()));
    expect(screen.getByTestId("lock-time").textContent).toBe(screen.getByTestId("status-time").textContent);
    phone(); expect(screen.getByTestId("status-time")).toHaveTextContent(expected(new Date()));
    click(/BoloRide/); await finishTune(); await advance(SIMULATED_CONNECTION_MS); click("Open Control Centre");
    expect(screen.getAllByTestId("status-time")).toHaveLength(1);
    expect(screen.getByTestId("status-time")).toHaveTextContent(expected(new Date()));
  });
  it("clock consumers use a single timer and resynchronize after visibility changes", () => {
    function ReadClock() { return <span>{useClock().time}</span>; }
    const view=render(<PhoneClock><ReadClock/><ReadClock/></PhoneClock>);
    expect(vi.getTimerCount()).toBe(1);
    vi.setSystemTime(new Date(2026,8,14,15,42)); fireEvent(document,new Event("visibilitychange"));
    expect(view.container.children[0].textContent).toBe(view.container.children[1].textContent);
    expect(vi.getTimerCount()).toBe(1);
  });
  it("reduced-motion controls remain usable", async () => {
    window.matchMedia=vi.fn(()=>({matches:true} as MediaQueryList));
    render(<PhoneDemo/>); call(); await finishTune(); await advance(SIMULATED_CONNECTION_MS); click("Open Control Centre"); click("Close Control Centre"); await advance(0);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
