import { createClient } from "./supabase/server";

export type DemoAccessStatus =
  | "not_requested"
  | "waitlisted"
  | "approved";

export type DemoAccessResponse = {
  status: DemoAccessStatus;
  position: number | null;
  granted_at: string | null;
};

export type DemoAuthorizationResult =
  | {
      authorized: true;
      accessToken: string;
      access: DemoAccessResponse;
    }
  | {
      authorized: false;
      reason:
        | "unauthenticated"
        | "not_approved"
        | "unavailable";
      access?: DemoAccessResponse;
    };

function getApiUrl(): string | null {
  const value =
    process.env.BOLORIDE_API_URL?.trim();

  if (!value) {
    return null;
  }

  return value.replace(/\/$/, "");
}

export async function authorizeDemoAccess(): Promise<DemoAuthorizationResult> {
  const apiUrl = getApiUrl();

  if (!apiUrl) {
    console.error(
      "[demo-access] BOLORIDE_API_URL is not configured.",
    );

    return {
      authorized: false,
      reason: "unavailable",
    };
  }

  const supabase = await createClient();

  const {
    data: { session },
    error: sessionError,
  } = await supabase.auth.getSession();

  if (
    sessionError ||
    !session?.access_token
  ) {
    return {
      authorized: false,
      reason: "unauthenticated",
    };
  }

  try {
    const response = await fetch(
      `${apiUrl}/api/demo/access`,
      {
        method: "GET",
        headers: {
          Authorization:
            `Bearer ${session.access_token}`,
        },
        cache: "no-store",
      },
    );

    if (response.status === 401) {
      return {
        authorized: false,
        reason: "unauthenticated",
      };
    }

    if (!response.ok) {
      console.error(
        "[demo-access] Authorization check failed:",
        response.status,
      );

      return {
        authorized: false,
        reason: "unavailable",
      };
    }

    const access =
      (await response.json()) as DemoAccessResponse;

    if (access.status !== "approved") {
      return {
        authorized: false,
        reason: "not_approved",
        access,
      };
    }

    return {
      authorized: true,
      accessToken: session.access_token,
      access,
    };
  } catch (error) {
    console.error(
      "[demo-access] Unable to reach BoloRide API:",
      error instanceof Error
        ? error.message
        : error,
    );

    return {
      authorized: false,
      reason: "unavailable",
    };
  }
}