export interface CallTransport {
  connect(signal: AbortSignal): Promise<void>;
  disconnect(): void | Promise<void>;
  setMuted(muted: boolean): void | Promise<void>;
  setVolume(volume: number): void;
  setNotificationHandler?(handler: (notification: RideNotification) => void): void;
}

export type RideNotification = {
  notification_id: string;
  type: "ride_booked" | "ride_cancelled";
  sender: "BR24IC42";
  ride_id: string;
  timestamp: string;
  payload: Record<string, string>;
};

export const SIMULATED_CONNECTION_MS = 5_000;

/** Explicit UI simulation: no network, microphone permission or remote media. */
export class SimulatedCallTransport implements CallTransport {
  private cancel: (() => void) | undefined;
  connect(signal: AbortSignal): Promise<void> {
    this.disconnect();
    return new Promise((resolve, reject) => {
      if (signal.aborted) { reject(new DOMException("Call cancelled", "AbortError")); return; }
      const finish = (cancelled: boolean) => {
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
        this.cancel = undefined;
        if (cancelled) reject(new DOMException("Call cancelled", "AbortError"));
        else resolve();
      };
      const abort = () => finish(true);
      const timer = setTimeout(() => finish(false), SIMULATED_CONNECTION_MS);
      this.cancel = abort;
      signal.addEventListener("abort", abort, { once: true });
    });
  }
  disconnect() { this.cancel?.(); }
  setMuted(_muted: boolean) { /* Demo microphone state is owned by the UI. */ }
  setVolume(_volume: number) { /* No remote media in simulation. */ }
  setNotificationHandler(_handler: (notification: RideNotification) => void) { /* No fake backend events. */ }
}
