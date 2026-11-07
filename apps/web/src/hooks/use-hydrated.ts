"use client";

import { useSyncExternalStore } from "react";

/** There is nothing to listen to: once the script has taken over, it stays. */
function subscribe(): () => void {
  return () => {
    // Nothing to stop listening to.
  };
}

/**
 * Whether the page's script has taken it over: false in the page as it is built or sent, and
 * while React hydrates it; true from then on. A form that only the script may send waits for it.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
