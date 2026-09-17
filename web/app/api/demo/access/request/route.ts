import {
  NextRequest,
  NextResponse,
} from "next/server";

const BOLORIDE_API_URL =
  process.env.BOLORIDE_API_URL?.replace(
    /\/$/,
    "",
  );

function configurationError() {
  return NextResponse.json(
    {
      detail:
        "BoloRide API is not configured.",
    },
    {
      status: 503,
    },
  );
}

export async function POST(
  request: NextRequest,
) {
  if (!BOLORIDE_API_URL) {
    return configurationError();
  }

  const authorization =
    request.headers.get("authorization");

  if (!authorization) {
    return NextResponse.json(
      {
        detail:
          "Authorization header is required.",
      },
      {
        status: 401,
      },
    );
  }

  try {
    const response = await fetch(
      `${BOLORIDE_API_URL}/api/demo/access/request`,
      {
        method: "POST",
        headers: {
          Authorization: authorization,
        },
        cache: "no-store",
      },
    );

    const body = await response.text();

    return new NextResponse(body, {
      status: response.status,
      headers: {
        "Content-Type":
          response.headers.get(
            "content-type",
          ) ?? "application/json",
      },
    });
  } catch (error) {
    console.error(
      "BoloRide access request API error:",
      error,
    );

    return NextResponse.json(
      {
        detail:
          "Unable to reach BoloRide API.",
      },
      {
        status: 502,
      },
    );
  }
}