import { NextResponse } from "next/server";
import { issueDemoToken } from "../../../lib/livekit-token";

export const runtime = "nodejs";

export async function POST() {
  try {
    const credentials = await issueDemoToken({
      LIVEKIT_URL: process.env.LIVEKIT_URL,
      LIVEKIT_API_KEY: process.env.LIVEKIT_API_KEY,
      LIVEKIT_API_SECRET: process.env.LIVEKIT_API_SECRET,
      LIVEKIT_AGENT_NAME: process.env.LIVEKIT_AGENT_NAME,
    });
    return NextResponse.json(credentials, {
      status: 201,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "Voice demo is not configured" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
