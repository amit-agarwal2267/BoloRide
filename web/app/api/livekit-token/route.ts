import { NextResponse } from "next/server";
import { issueDemoToken } from "../../../lib/livekit-token";

export const runtime = "nodejs";

export async function POST() {
  try {
    const credentials = await issueDemoToken({
      LIVEKIT_URL: process.env.LIVEKIT_URL,
      LIVEKIT_HTTP_URL: process.env.LIVEKIT_HTTP_URL,
      LIVEKIT_BROWSER_URL: process.env.LIVEKIT_BROWSER_URL,
      LIVEKIT_API_KEY: process.env.LIVEKIT_API_KEY,
      LIVEKIT_API_SECRET: process.env.LIVEKIT_API_SECRET,
      LIVEKIT_AGENT_NAME: process.env.LIVEKIT_AGENT_NAME,
    });
    return NextResponse.json(credentials, {
      status: 201,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    console.error(
      "[livekit-token] Failed to create token or dispatch agent:",
      error instanceof Error ? error.message : error,
    );

    return NextResponse.json(
      { error: "Voice demo is unavailable" },
      {
        status: 503,
        headers: { "Cache-Control": "no-store" },
      },
    );
  }
}
