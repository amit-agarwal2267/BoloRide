import { NextResponse } from "next/server";

import { authorizeDemoAccess } from "../../../lib/demo-access";
import { issueDemoToken } from "../../../lib/livekit-token";
import { endDemoPhoneCall, startDemoPhoneCall } from "../../../lib/demo-phone";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST() {
  const authorization =
    await authorizeDemoAccess();

  if (!authorization.authorized) {
    if (
      authorization.reason ===
      "unauthenticated"
    ) {
      return NextResponse.json(
        {
          error: "Authentication required",
        },
        {
          status: 401,
          headers: {
            "Cache-Control": "no-store",
          },
        },
      );
    }

    if (
      authorization.reason ===
      "not_approved"
    ) {
      return NextResponse.json(
        {
          error: "Demo access not approved",
        },
        {
          status: 403,
          headers: {
            "Cache-Control": "no-store",
          },
        },
      );
    }

    return NextResponse.json(
      {
        error:
          "Unable to verify demo access",
      },
      {
        status: 503,
        headers: {
          "Cache-Control": "no-store",
        },
      },
    );
  }

  let callLease: Awaited<ReturnType<typeof startDemoPhoneCall>> | null = null;
  try {
    callLease = await startDemoPhoneCall(authorization);
    const credentials =
      await issueDemoToken({
        LIVEKIT_URL:
          process.env.LIVEKIT_URL,
        LIVEKIT_HTTP_URL:
          process.env.LIVEKIT_HTTP_URL,
        LIVEKIT_BROWSER_URL:
          process.env.LIVEKIT_BROWSER_URL,
        LIVEKIT_API_KEY:
          process.env.LIVEKIT_API_KEY,
        LIVEKIT_API_SECRET:
          process.env.LIVEKIT_API_SECRET,
        LIVEKIT_AGENT_NAME:
          process.env.LIVEKIT_AGENT_NAME,
      }, callLease.phone_number);

    return NextResponse.json(
      { ...credentials, callId: callLease.call_id, maskedNumber: callLease.masked_number },
      {
        status: 201,
        headers: {
          "Cache-Control": "no-store",
        },
      },
    );
  } catch (error) {
    if (callLease) {
      await endDemoPhoneCall(authorization, callLease.call_id).catch(() => undefined);
    }
    console.error(
      "[livekit-token] Failed to create token or dispatch agent:",
      error instanceof Error
        ? error.message
        : error,
    );

    return NextResponse.json(
      {
        error:
          "Voice demo is unavailable",
      },
      {
        status: 503,
        headers: {
          "Cache-Control": "no-store",
        },
      },
    );
  }
}