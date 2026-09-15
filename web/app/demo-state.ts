export const DEMO_NUMBER = "18002582334";
export const DISPLAY_DEMO_NUMBER = "1800-258-2334";

export type PhoneScreen =
  | "locked"
  | "home"
  | "messages"
  | "message-thread"
  | "phone-recents"
  | "phone-keypad"
  | "calling-tune"
  | "connecting"
  | "connected"
  | "call-ended"
  | "call-error";

export type DemoState = {
  screen: PhoneScreen;
  digits: string;
  previousPhoneScreen: "phone-recents" | "phone-keypad";
  dialog: null | "app-error" | "incorrect-number";
};

export type DemoAction =
  | { type: "unlock" }
  | { type: "home" }
  | { type: "open-phone" }
  | { type: "open-messages" }
  | { type: "open-message-thread" }
  | { type: "open-recents" }
  | { type: "open-keypad" }
  | { type: "open-unavailable-app" }
  | { type: "close-dialog" }
  | { type: "append-digit"; digit: string }
  | { type: "delete-digit" }
  | { type: "clear-digits" }
  | { type: "select-boloride" }
  | { type: "invalid-number" }
  | { type: "start-call" }
  | { type: "tune-ended" }
  | { type: "connected" }
  | { type: "call-ended" }
  | { type: "call-error" }
  | { type: "retry" };

export const initialDemoState: DemoState = {
  screen: "locked",
  digits: "",
  previousPhoneScreen: "phone-recents",
  dialog: null,
};

export function normalizeDialedNumber(value: string): string {
  return value.replace(/[\s()\-]/g, "");
}

export function formatDemoNumber(value: string): string {
  const normalized = normalizeDialedNumber(value).slice(0, DEMO_NUMBER.length);
  if (normalized.length <= 4) return normalized;
  if (normalized.length <= 7) return `${normalized.slice(0, 4)}-${normalized.slice(4)}`;
  return `${normalized.slice(0, 4)}-${normalized.slice(4, 7)}-${normalized.slice(7)}`;
}

export function demoReducer(state: DemoState, action: DemoAction): DemoState {
  switch (action.type) {
    case "unlock":
      return { ...state, screen: "home", dialog: null };
    case "home":
      return { ...state, screen: "home", dialog: null };
    case "open-phone":
    case "open-recents":
      return { ...state, screen: "phone-recents", previousPhoneScreen: "phone-recents", dialog: null };
    case "open-messages":
      return { ...state, screen: "messages", dialog: null };
    case "open-message-thread":
      return { ...state, screen: "message-thread", dialog: null };
    case "open-keypad":
      return { ...state, screen: "phone-keypad", previousPhoneScreen: "phone-keypad", dialog: null };
    case "open-unavailable-app":
      return { ...state, dialog: "app-error" };
    case "close-dialog":
      return { ...state, dialog: null };
    case "append-digit":
      return { ...state, digits: (state.digits + action.digit).slice(0, DEMO_NUMBER.length) };
    case "delete-digit":
      return { ...state, digits: state.digits.slice(0, -1) };
    case "clear-digits":
      return { ...state, digits: "" };
    case "select-boloride":
      return { ...state, digits: DEMO_NUMBER, screen: "phone-recents", previousPhoneScreen: "phone-recents" };
    case "invalid-number":
      return { ...state, dialog: "incorrect-number" };
    case "start-call":
      return { ...state, screen: "calling-tune", dialog: null };
    case "tune-ended":
      return { ...state, screen: "connecting", dialog: null };
    case "connected":
      return { ...state, screen: "connected", dialog: null };
    case "call-ended":
      return { ...state, screen: "call-ended", dialog: null };
    case "call-error":
      return { ...state, screen: "call-error", dialog: null };
    case "retry":
      return { ...state, screen: state.previousPhoneScreen, dialog: null };
  }
}
