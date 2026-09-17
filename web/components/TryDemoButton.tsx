"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight, Phone } from "@phosphor-icons/react";

import AuthModal from "./AuthModal";
import WaitlistModal from "./WaitlistModal";
import { createClient } from "../lib/supabase/client";

type TryDemoButtonProps = {
  variant?: "primary" | "nav";
  label?: string;
  showPhoneIcon?: boolean;
};

type DemoAccessResponse =
  | {
      status: "not_requested";
      position: null;
      granted_at: null;
    }
  | {
      status: "waitlisted";
      position: number;
      granted_at: null;
    }
  | {
      status: "approved";
      position: null;
      granted_at: string | null;
    };

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_BOLORIDE_API_URL ??
  "http://localhost:8000"
).replace(/\/$/, "");

export default function TryDemoButton({
  variant = "primary",
  label = "Try Demo",
  showPhoneIcon = false,
}: TryDemoButtonProps) {
  const router = useRouter();

  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [waitlistModalOpen, setWaitlistModalOpen] = useState(false);

  const [waitlistPosition, setWaitlistPosition] = useState<number | null>(
    null,
  );

  const [checkingAccess, setCheckingAccess] = useState(false);

  async function getAccessStatus(
    accessToken: string,
  ): Promise<DemoAccessResponse> {
    const response = await fetch(
      `${API_BASE_URL}/api/demo/access`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      },
    );

    if (response.status === 401) {
      throw new Error("UNAUTHORIZED");
    }

    if (!response.ok) {
      throw new Error(
        `Unable to check demo access. HTTP ${response.status}`,
      );
    }

    return (await response.json()) as DemoAccessResponse;
  }

  async function requestAccess(
    accessToken: string,
  ): Promise<DemoAccessResponse> {
    const response = await fetch(
      `${API_BASE_URL}/api/demo/access/request`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      },
    );

    if (response.status === 401) {
      throw new Error("UNAUTHORIZED");
    }

    if (!response.ok) {
      throw new Error(
        `Unable to request demo access. HTTP ${response.status}`,
      );
    }

    return (await response.json()) as DemoAccessResponse;
  }

  function handleAccessResult(
    access: DemoAccessResponse,
  ): boolean {
    if (access.status === "approved") {
      setAuthModalOpen(false);
      setWaitlistModalOpen(false);
      setWaitlistPosition(null);

      router.push("/demo");

      return true;
    }

    if (access.status === "waitlisted") {
      setAuthModalOpen(false);

      setWaitlistPosition(access.position);
      setWaitlistModalOpen(true);

      return true;
    }

    return false;
  }

  async function resolveDemoAccess() {
    if (checkingAccess) {
      return;
    }

    setCheckingAccess(true);

    try {
      const supabase = createClient();

      const {
        data: { session },
        error: sessionError,
      } = await supabase.auth.getSession();

      if (sessionError) {
        console.error(
          "Unable to read Supabase session:",
          sessionError.message,
        );

        setAuthModalOpen(true);
        return;
      }

      if (!session) {
        setAuthModalOpen(true);
        return;
      }

      const accessToken = session.access_token;

      /*
       * First check whether this user already:
       *
       * - has access
       * - is waitlisted
       * - has never requested access
       */
      const access = await getAccessStatus(accessToken);

      const handled = handleAccessResult(access);

      if (handled) {
        return;
      }

      /*
       * The authenticated user has never requested demo access.
       *
       * Create their waitlist request now.
       */
      if (access.status === "not_requested") {
        const requestedAccess = await requestAccess(
          accessToken,
        );

        const requestHandled =
          handleAccessResult(requestedAccess);

        if (!requestHandled) {
          throw new Error(
            "Demo access request returned an unexpected state.",
          );
        }
      }
    } catch (error) {
      console.error(
        "Unable to resolve BoloRide demo access:",
        error,
      );

      if (
        error instanceof Error &&
        error.message === "UNAUTHORIZED"
      ) {
        const supabase = createClient();

        await supabase.auth.signOut();

        setWaitlistModalOpen(false);
        setWaitlistPosition(null);
        setAuthModalOpen(true);

        return;
      }

      window.alert(
        "Unable to check demo access right now. Please try again.",
      );
    } finally {
      setCheckingAccess(false);
    }
  }

  async function handleTryDemo() {
    await resolveDemoAccess();
  }

  async function handleAuthenticated() {
    /*
     * AuthModal calls this immediately after a successful sign-in.
     *
     * We close the auth modal and immediately check the user's
     * actual authorization state from the BoloRide backend.
     */
    setAuthModalOpen(false);

    await resolveDemoAccess();
  }

  return (
    <>
      <button
        type="button"
        className={
          variant === "nav"
            ? "button button--ink"
            : "button button--red"
        }
        onClick={handleTryDemo}
        disabled={checkingAccess}
      >
        {showPhoneIcon && <Phone weight="fill" />}

        {checkingAccess ? "Checking..." : label}

        {!showPhoneIcon && (
          <ArrowUpRight weight="bold" />
        )}
      </button>

      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        onAuthenticated={handleAuthenticated}
      />

      <WaitlistModal
        isOpen={waitlistModalOpen}
        position={waitlistPosition}
        onClose={() => setWaitlistModalOpen(false)}
      />
    </>
  );
}