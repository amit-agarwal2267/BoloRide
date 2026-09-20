import { AccessToken, AgentDispatchClient } from "livekit-server-sdk";
import { TrackSource } from "@livekit/protocol";
import { randomUUID } from "node:crypto";

export type TokenEnvironment = {
  LIVEKIT_URL?: string;
  LIVEKIT_HTTP_URL?: string;
  LIVEKIT_BROWSER_URL?: string;
  LIVEKIT_API_KEY?: string;
  LIVEKIT_API_SECRET?: string;
  LIVEKIT_AGENT_NAME?: string;
};

function toHttpUrl(websocketUrl: string): string {
  if (websocketUrl.startsWith("wss://")) {
    return `https://${websocketUrl.slice("wss://".length)}`;
  }

  if (websocketUrl.startsWith("ws://")) {
    return `http://${websocketUrl.slice("ws://".length)}`;
  }

  throw new Error("LIVEKIT_URL must be a WebSocket URL");
}

export async function issueDemoToken(environment: TokenEnvironment, demoPhone?: string) {
  const internalUrl = environment.LIVEKIT_URL;
  const httpUrl = environment.LIVEKIT_HTTP_URL;
  const browserUrl = environment.LIVEKIT_BROWSER_URL;

  const apiKey = environment.LIVEKIT_API_KEY;
  const apiSecret = environment.LIVEKIT_API_SECRET;
  const agentName = environment.LIVEKIT_AGENT_NAME?.trim() || "boloride-dev";

  if (!internalUrl || !httpUrl || !browserUrl || !apiKey || !apiSecret) {
    throw new Error("LiveKit server configuration is incomplete");
  }

  if (!browserUrl || !apiKey || !apiSecret) {
    throw new Error("LiveKit server configuration is incomplete");
  }

  if (!browserUrl.startsWith("wss://") && !browserUrl.startsWith("ws://")) {
    throw new Error("LIVEKIT_URL must be a WebSocket URL");
  }

  const roomName = `boloride-web-${randomUUID()}`;
  const participantIdentity = `browser-demo-${randomUUID()}`;

  const token = new AccessToken(apiKey, apiSecret, {
    identity: participantIdentity,
    name: "BoloRide Browser Demo",
    ttl: "10m",
  });

  token.addGrant({
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canPublishData: false,
    canPublishSources: [TrackSource.MICROPHONE],
    canSubscribe: true,
  });

  /*
   * IMPORTANT:
   * Explicitly dispatch the BoloRide worker to this room.
   *
   * This mirrors boloride_voice_test.py, which is already known
   * to establish a working frontend -> LiveKit -> agent connection.
   */
  const dispatchClient = new AgentDispatchClient(httpUrl, apiKey, apiSecret);

  try {
    console.log("[livekit-token] dispatching", {
      roomName,
      agentName,
      livekitHttpUrl: toHttpUrl(browserUrl),
    });

    const dispatch = await dispatchClient.createDispatch(roomName, agentName, {
      metadata: JSON.stringify({
        client: "boloride-web-demo",
        mode: "microphone",
        transport: "browser",
        ...(demoPhone ? { phone_number: demoPhone } : {}),
      }),
    });

    console.log("[livekit-token] dispatch created", {
      roomName,
      agentName,
      dispatchId: dispatch.id,
    });
  } catch (error) {
    console.error("[livekit-token] dispatch FAILED");

    if (error instanceof Error) {
      console.error("name:", error.name);
      console.error("message:", error.message);

      const cause = (error as Error & { cause?: unknown }).cause;
      console.error("cause:", cause);
    } else {
      console.error(error);
    }

    throw error;
  }

  return {
    serverUrl: browserUrl,
    participantToken: await token.toJwt(),
    roomName,
  };
}
