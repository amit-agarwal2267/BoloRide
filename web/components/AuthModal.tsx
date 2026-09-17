"use client";

import { FormEvent, useState } from "react";
import { X } from "@phosphor-icons/react";

import { createClient } from "../lib/supabase/client";

type AuthMode = "signup" | "signin";

type AuthModalProps = {
  isOpen: boolean;
  onClose: () => void;
  onAuthenticated: () => void | Promise<void>;
};

export default function AuthModal({
  isOpen,
  onClose,
  onAuthenticated,
}: AuthModalProps) {
  const [mode, setMode] = useState<AuthMode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  if (!isOpen) {
    return null;
  }

  function resetFeedback() {
    setError(null);
    setMessage(null);
  }

  function switchMode(nextMode: AuthMode) {
    setMode(nextMode);
    setPassword("");
    resetFeedback();
  }

  async function handleSignUp() {
    const supabase = createClient();

    const { data, error } = await supabase.auth.signUp({
      email: email.trim(),
      password,
    });

    if (error) {
      throw error;
    }

    if (!data.session) {
      setMessage(
        "Account created. Check your email to verify your account, then sign in.",
      );
      return;
    }

    await onAuthenticated();
  }

  async function handleSignIn() {
    const supabase = createClient();

    const { error } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });

    if (error) {
      throw error;
    }

    await onAuthenticated();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (loading) {
      return;
    }

    resetFeedback();

    const normalizedEmail = email.trim();

    if (!normalizedEmail) {
      setError("Enter your email address.");
      return;
    }

    if (!password) {
      setError("Enter your password.");
      return;
    }

    if (mode === "signup" && password.length < 8) {
      setError("Password must contain at least 8 characters.");
      return;
    }

    setLoading(true);

    try {
      if (mode === "signup") {
        await handleSignUp();
      } else {
        await handleSignIn();
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="request-access-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !loading) {
          onClose();
        }
      }}
    >
      <div
        className="request-access-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-modal-title"
      >
        <button
          type="button"
          className="request-access-close"
          aria-label="Close"
          onClick={onClose}
          disabled={loading}
        >
          <X weight="bold" />
        </button>

        <div className="request-access-header">
          <p className="mono-kicker">
            <span />
            BOLORIDE DEMO
          </p>

          <h2 id="auth-modal-title">
            {mode === "signin" ? "Sign in to continue" : "Create your account"}
          </h2>

          <p>
            {mode === "signin"
              ? "Sign in to check your access to the live BoloRide voice demo."
              : "Create an account to request access to the live BoloRide voice demo."}
          </p>
        </div>

        <form className="request-access-form" onSubmit={handleSubmit}>
          <label htmlFor="boloride-auth-email">
            Email
            <input
              id="boloride-auth-email"
              name="email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={loading}
              required
            />
          </label>

          <label htmlFor="boloride-auth-password">
            Password
            <input
              id="boloride-auth-password"
              name="password"
              type="password"
              autoComplete={
                mode === "signup" ? "new-password" : "current-password"
              }
              placeholder="Enter your password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={loading}
              minLength={mode === "signup" ? 8 : undefined}
              required
            />
          </label>

          {error && (
            <p
              className="request-access-feedback request-access-feedback--error"
              role="alert"
            >
              {error}
            </p>
          )}

          {message && (
            <p
              className="request-access-feedback request-access-feedback--success"
              role="status"
            >
              {message}
            </p>
          )}

          <button
            type="submit"
            className="button button--red request-access-submit"
            disabled={loading}
          >
            {loading
              ? "Please wait..."
              : mode === "signin"
                ? "Sign In"
                : "Create Account"}
          </button>
        </form>

        <div className="request-access-switch">
          {mode === "signin" ? (
            <p>
              Don&apos;t have an account?{" "}
              <button
                type="button"
                onClick={() => switchMode("signup")}
                disabled={loading}
              >
                Create one
              </button>
            </p>
          ) : (
            <p>
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => switchMode("signin")}
                disabled={loading}
              >
                Sign in
              </button>
            </p>
          )}
        </div>

        <p className="request-access-note">
          Access to the live voice demo is limited.
        </p>
      </div>
    </div>
  );
}