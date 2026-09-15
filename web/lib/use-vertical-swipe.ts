"use client";
import { useRef, useState, type PointerEvent, type MouseEvent } from "react";

/** Stable container, shared pointer lifecycle; decorative animation follows offset.
 * Measurements are in screen CSS pixels, including when the demo is scaled to fit. */
export function useVerticalSwipe({ direction, onComplete, enabled = true, startRange = [0, 1], threshold = 64, ignoreControls = false }: {
  direction: "up" | "down"; onComplete: () => void; enabled?: boolean;
  startRange?: [number, number]; threshold?: number; ignoreControls?: boolean;
}) {
  const gesture = useRef<{ id: number; x: number; y: number; scale: number; horizontal: boolean } | null>(null);
  const suppressClick = useRef(false);
  const [offset, setOffset] = useState(0);
  const reset = () => { gesture.current = null; setOffset(0); };
  const delta = (event: PointerEvent<HTMLElement>) => {
    const g = gesture.current;
    if (!g || event.pointerId !== g.id) return null;
    const x = (event.clientX - g.x) / g.scale, y = (event.clientY - g.y) / g.scale;
    if (Math.abs(x) > 12 && Math.abs(x) > Math.abs(y) * 1.2) g.horizontal = true;
    return { x, y, g };
  };
  return { offset, handlers: {
    onPointerDown(event: PointerEvent<HTMLElement>) {
      if (!enabled || gesture.current || event.button > 0) return;
      suppressClick.current = false;
      if (ignoreControls && (event.target as HTMLElement).closest("button,input,a")) return;
      const rect = event.currentTarget.getBoundingClientRect();
      const fraction = (event.clientY - rect.top) / rect.height;
      if (fraction < startRange[0] || fraction > startRange[1]) return;
      gesture.current = { id: event.pointerId, x: event.clientX, y: event.clientY, scale: rect.height / (event.currentTarget.offsetHeight || rect.height) || 1, horizontal: false };
    },
    onPointerMove(event: PointerEvent<HTMLElement>) {
      const d = delta(event); if (!d) return;
      if (Math.abs(d.y) > 8 || d.g.horizontal) { suppressClick.current = true; event.currentTarget.setPointerCapture?.(event.pointerId); }
      setOffset(d.g.horizontal ? 0 : direction === "up" ? Math.min(0, d.y) : Math.max(0, d.y));
    },
    onPointerUp(event: PointerEvent<HTMLElement>) {
      const d = delta(event); if (!d) return; reset();
      if (Math.abs(d.y) > 8 || d.g.horizontal) suppressClick.current = true;
      if (!d.g.horizontal && Math.abs(d.y) > Math.abs(d.x) * 1.2 && (direction === "up" ? -d.y : d.y) >= threshold) onComplete();
    },
    onPointerCancel(event: PointerEvent<HTMLElement>) {
      if (gesture.current?.id === event.pointerId) reset();
    },
    onLostPointerCapture(event: PointerEvent<HTMLElement>) {
      // Touch starts with implicit capture on the child hit target. Transferring
      // capture to this container emits a bubbling loss from that child;
      // it is not cancellation of the container's gesture.
      if (event.target === event.currentTarget && gesture.current?.id === event.pointerId) reset();
    },
    onClickCapture(event: MouseEvent<HTMLElement>) {
      if (suppressClick.current && event.detail !== 0) { event.preventDefault(); event.stopPropagation(); suppressClick.current = false; }
    },
  } };
}
