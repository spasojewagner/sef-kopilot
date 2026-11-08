import type { Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

/**
 * What an MCP client asks of the person it sends to the web application, and their decision
 * (ADR-0044). The API's authorization server keeps the request for ten minutes; only a person,
 * signed in, reads and decides it.
 */

/** What a client asks to do for the person deciding (`GET /oauth/requests/{id}`). */
export type AuthorizationRequest = Schemas["AuthorizationRequest"];

/** Where to send the person once they have decided: the client's address, with its answer. */
export type Decision = Schemas["Decision"];

function requestPath(id: string): string {
  return `/oauth/requests/${encodeURIComponent(id)}`;
}

/** The request ``id``, while it waits for a decision. */
export function getAuthorizationRequest(
  id: string,
  signal?: AbortSignal,
): Promise<AuthorizationRequest> {
  return authorized<AuthorizationRequest>(requestPath(id), { signal });
}

/** Lets the client do what it asked, within what the visitor's role grants them. */
export function approveAuthorizationRequest(id: string): Promise<Decision> {
  return authorized<Decision>(`${requestPath(id)}/approval`, {
    method: "POST",
  });
}

/** Refuses the client's request. */
export function refuseAuthorizationRequest(id: string): Promise<Decision> {
  return authorized<Decision>(`${requestPath(id)}/refusal`, {
    method: "POST",
  });
}

/** Where a client's redirect URI takes the person, as they can tell it. */
export interface Destination {
  /** A web address's host and port, or an application's own scheme, with its host if any. */
  address: string;
  /**
   * Whether it is an application on the person's own computer rather than a site: the loopback
   * interface, or a scheme of the application's own (RFC 8252).
   */
  local: boolean;
}

const LOOPBACK = new Set(["127.0.0.1", "[::1]", "localhost"]);

/**
 * Where ``uri`` takes the person once they decide, shortened to what they can check: the host
 * of a web address (`claude.ai`), or the scheme of an application's own address, with its host
 * if it has one (`cursor://anysphere.cursor-mcp`).
 */
export function destinationOf(uri: string): Destination {
  let url: URL;
  try {
    url = new URL(uri);
  } catch {
    return { address: uri, local: false };
  }
  if (url.protocol === "https:" || url.protocol === "http:") {
    return { address: url.host, local: LOOPBACK.has(url.hostname) };
  }
  return {
    address: url.host ? `${url.protocol}//${url.host}` : url.protocol,
    local: true,
  };
}

/**
 * The host that published the description of a client known by its metadata document, whose
 * ``client_id`` is that document's `https` address (ADR-0045); null for a registered client,
 * whose ``client_id`` the server made up. The server fetched the description from this host,
 * so whoever runs it stands behind the client, whatever name the client gives itself.
 */
export function publisherOf(clientId: string): string | null {
  if (!clientId.startsWith("https://")) {
    return null;
  }
  try {
    return new URL(clientId).host;
  } catch {
    return null;
  }
}
