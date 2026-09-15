import { describe, expect, it } from "vitest";
import { issueDemoToken } from "../lib/livekit-token";

function payload(jwt: string) {
  return JSON.parse(Buffer.from(jwt.split(".")[1], "base64url").toString("utf8"));
}

const environment = {
  LIVEKIT_URL: "wss://demo.livekit.cloud",
  LIVEKIT_API_KEY: "ci_demo_key",
  LIVEKIT_API_SECRET: "ci_demo_secret_never_for_browser",
  LIVEKIT_AGENT_NAME: "boloride-dev",
};

describe("browser demo token", () => {
  it("is short-lived, room-scoped, minimal, and explicitly dispatches the agent", async () => {
    const result = await issueDemoToken(environment);
    const claims = payload(result.participantToken);

    expect(result.roomName).toMatch(/^boloride-web-[0-9a-f-]+$/);
    expect(claims.video).toMatchObject({
      room: result.roomName,
      roomJoin: true,
      canPublish: true,
      canPublishData: false,
      canSubscribe: true,
    });
    expect(claims.roomConfig.agents[0].agentName).toBe("boloride-dev");
    expect(claims.roomConfig.agents[0].metadata).toBe('{"transport":"browser"}');
    expect(claims.exp).toBeGreaterThanOrEqual(Math.floor(Date.now() / 1000) + 590);
    expect(claims.exp).toBeLessThanOrEqual(Math.floor(Date.now() / 1000) + 600);
  });

  it("never returns or embeds the API secret and creates fresh identities", async () => {
    const first = await issueDemoToken(environment);
    const second = await issueDemoToken(environment);
    const serialized = JSON.stringify(first);

    expect(serialized).not.toContain(environment.LIVEKIT_API_SECRET);
    expect(payload(first.participantToken).sub).not.toBe(payload(second.participantToken).sub);
    expect(first.roomName).not.toBe(second.roomName);
  });

  it("rejects incomplete server configuration", async () => {
    await expect(issueDemoToken({})).rejects.toThrow("incomplete");
  });
});
