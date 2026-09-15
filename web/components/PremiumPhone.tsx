import { type ReactNode, type CSSProperties } from "react";
import { PhoneStatusBar } from "./PhoneStatusBar";
import { useVerticalSwipe } from "../lib/use-vertical-swipe";

export function PremiumPhone({ children, connected = false, microphoneActive = false, controlsOpen = false, onOpenControls }: { children: ReactNode; connected?: boolean; microphoneActive?: boolean; controlsOpen?: boolean; onOpenControls?: () => void }) {
  const { offset, handlers } = useVerticalSwipe({ direction: "down", onComplete: () => onOpenControls?.(), enabled: connected && !controlsOpen, startRange: [0, .2], threshold: 58 });
  return (
    <div className="device-scene">
      <div className="device-shadow" aria-hidden="true" />
      <section className="premium-phone" aria-label="BoloRide demonstration phone">
        <span className="side-button side-button--action" aria-hidden="true" />
        <span className="side-button side-button--volume-up" aria-hidden="true" />
        <span className="side-button side-button--volume-down" aria-hidden="true" />
        <span className="side-button side-button--power" aria-hidden="true" />
        <div className={`phone-glass ${connected ? "phone-glass--connected" : ""}`} data-testid="phone-glass" {...handlers} style={{ "--control-pull": `${Math.min(offset * .25, 20)}px` } as CSSProperties}>
          <div className="dynamic-island" aria-hidden="true"><i /></div>
          <PhoneStatusBar callActive={connected} microphoneActive={microphoneActive} onOpenControls={onOpenControls}/>
          {children}
          <div className="home-indicator" aria-hidden="true" />
          <div className="screen-reflection" aria-hidden="true" />
        </div>
      </section>
    </div>
  );
}
