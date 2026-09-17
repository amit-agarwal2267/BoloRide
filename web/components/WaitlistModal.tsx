"use client";

import { X } from "@phosphor-icons/react";

type WaitlistModalProps = {
  isOpen: boolean;
  position: number | null;
  onClose: () => void;
};

export default function WaitlistModal({
  isOpen,
  position,
  onClose,
}: WaitlistModalProps) {
  if (!isOpen) {
    return null;
  }

  return (
    <div
      className="request-access-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        className="request-access-modal waitlist-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="waitlist-title"
      >
        <button
          type="button"
          className="request-access-close"
          aria-label="Close"
          onClick={onClose}
        >
          <X weight="bold" />
        </button>

        <div className="request-access-header">
          <p className="mono-kicker">
            <span />
            BOLORIDE DEMO
          </p>

          <h2 id="waitlist-title">Waitlist</h2>

          <p>You are in the queue.</p>
        </div>

        <div className="waitlist-position">
          <span>Your position in the queue is</span>

          <strong>
            {position !== null ? `#${position}` : "—"}
          </strong>
        </div>

        <p className="request-access-note">
          We&apos;ll keep your place in the queue. Sign in again later to
          check your access.
        </p>

        <button
          type="button"
          className="button button--red request-access-submit"
          onClick={onClose}
        >
          Got it
        </button>
      </div>
    </div>
  );
}