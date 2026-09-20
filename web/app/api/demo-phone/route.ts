import { NextRequest, NextResponse } from "next/server";
import { authorizeDemoAccess } from "../../../lib/demo-access";
import { endDemoPhoneCall, getDemoPhone, rollDemoPhone } from "../../../lib/demo-phone";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function denied(reason: string) {
  return NextResponse.json(
    { error: reason === "unauthenticated" ? "Authentication required" : "Demo access required" },
    { status: reason === "unauthenticated" ? 401 : 403, headers: { "Cache-Control": "no-store" } },
  );
}

export async function GET() {
  const authorization = await authorizeDemoAccess();
  if (!authorization.authorized) return denied(authorization.reason);
  try {
    return NextResponse.json(await getDemoPhone(authorization), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    const status = (error as Error & { status?: number }).status ?? 503;
    return NextResponse.json({ error: error instanceof Error ? error.message : "Demo phone unavailable" }, { status });
  }
}

export async function POST(request: NextRequest) {
  const authorization = await authorizeDemoAccess();
  if (!authorization.authorized) return denied(authorization.reason);
  const body = await request.json().catch(() => ({})) as { action?: string; call_id?: string };
  try {
    if (body.action === "roll") {
      return NextResponse.json(await rollDemoPhone(authorization), {
        headers: { "Cache-Control": "no-store" },
      });
    }
    if (body.action === "end" && body.call_id) {
      return NextResponse.json(await endDemoPhoneCall(authorization, body.call_id), {
        headers: { "Cache-Control": "no-store" },
      });
    }
    return NextResponse.json({ error: "Invalid demo phone action" }, { status: 400 });
  } catch (error) {
    const status = (error as Error & { status?: number }).status ?? 503;
    return NextResponse.json({ error: error instanceof Error ? error.message : "Demo phone unavailable" }, { status });
  }
}
