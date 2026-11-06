import { queryOptions } from "@tanstack/react-query";

import { getHealth } from "@/lib/api";

/**
 * The questions the pages ask the API, each with the key its answers are kept under. A page
 * asks with `useQuery(healthQuery)`; the key also names the answer to refresh or to forget.
 */

/** Whether the API answers, and which version it runs. */
export const healthQuery = queryOptions({
  queryKey: ["api", "health"],
  queryFn: ({ signal }) => getHealth(signal),
});
