import type { DemoAuthorizationResult } from "./demo-access";

export type DemoPhonePublic = {
  masked_number: string;
  in_use: boolean;
};

export type DemoPhoneCall = DemoPhonePublic & {
  phone_number: string;
  call_id: string;
  expires_at: string;
};

function apiUrl(): string {
  const value = process.env.BOLORIDE_API_URL?.trim();
  if (!value) throw new Error("BOLORIDE_API_URL is not configured");
  return value.replace(/\/$/, "");
}

async function callBackend<T>(
  authorization: Extract<DemoAuthorizationResult, { authorized: true }>,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${apiUrl()}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${authorization.accessToken}`,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body.detail || "Demo phone request failed") as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return response.json() as Promise<T>;
}

export const getDemoPhone = (authorization: Extract<DemoAuthorizationResult, { authorized: true }>) =>
  callBackend<DemoPhonePublic>(authorization, "/api/demo/phone");

export const rollDemoPhone = (authorization: Extract<DemoAuthorizationResult, { authorized: true }>) =>
  callBackend<DemoPhonePublic>(authorization, "/api/demo/phone/roll", { method: "POST" });

export const startDemoPhoneCall = (authorization: Extract<DemoAuthorizationResult, { authorized: true }>) =>
  callBackend<DemoPhoneCall>(authorization, "/api/demo/phone/call/start", { method: "POST" });

export const endDemoPhoneCall = (
  authorization: Extract<DemoAuthorizationResult, { authorized: true }>,
  callId: string,
) => callBackend<DemoPhonePublic>(authorization, "/api/demo/phone/call/end", {
  method: "POST",
  body: JSON.stringify({ call_id: callId }),
});
