import { RoomAgentDispatch, RoomConfiguration, TrackSource } from "@livekit/protocol";
import { AccessToken } from "livekit-server-sdk";
import { randomUUID } from "node:crypto";

export type TokenEnvironment = {
  LIVEKIT_URL?: string;
  LIVEKIT_API_KEY?: string;
  LIVEKIT_API_SECRET?: string;
  LIVEKIT_AGENT_NAME?: string;
};

export async function issueDemoToken(environment: TokenEnvironment) {
  const url = environment.LIVEKIT_URL;
  const apiKey = environment.LIVEKIT_API_KEY;
  const apiSecret = environment.LIVEKIT_API_SECRET;
  const agentName = environment.LIVEKIT_AGENT_NAME ?? "boloride-dev";
  if (!url || !apiKey || !apiSecret) {
    throw new Error("LiveKit server configuration is incomplete");
  }
  if (!url.startsWith("wss://") && !url.startsWith("ws://")) {
    throw new Error("LIVEKIT_URL must be a WebSocket URL");
  }

  const suffix = randomUUID();
  const roomName = `boloride-web-${suffix}`;
  const participantIdentity = `browser-demo-${randomUUID()}`;
  const token = new AccessToken(apiKey, apiSecret, {
    identity: participantIdentity,
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
  token.roomConfig = new RoomConfiguration({
    agents: [
      new RoomAgentDispatch({
        agentName,
        metadata: JSON.stringify({ transport: "browser" }),
      }),
    ],
  });

  return { serverUrl: url, participantToken: await token.toJwt(), roomName };
}
