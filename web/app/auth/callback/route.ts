import {
  NextRequest,
  NextResponse,
} from "next/server";

import { createClient } from "../../../lib/supabase/server";

export async function GET(
  request: NextRequest,
) {
  const requestUrl = new URL(request.url);

  const code =
    requestUrl.searchParams.get("code");

  let next =
    requestUrl.searchParams.get("next") ??
    "/";

  if (!next.startsWith("/")) {
    next = "/";
  }

  if (code) {
    const supabase = await createClient();

    const { error } =
      await supabase.auth.exchangeCodeForSession(
        code,
      );

    if (!error) {
      const redirectUrl =
        request.nextUrl.clone();

      redirectUrl.pathname = next;
      redirectUrl.search = "";

      return NextResponse.redirect(
        redirectUrl,
      );
    }

    console.error(
      "Unable to exchange Google OAuth code:",
      error.message,
    );
  }

  const errorUrl =
    request.nextUrl.clone();

  errorUrl.pathname = "/";
  errorUrl.searchParams.set(
    "auth_error",
    "google",
  );

  return NextResponse.redirect(errorUrl);
}