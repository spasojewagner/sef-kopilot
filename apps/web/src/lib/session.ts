/**
 * The signed-in visitor's session in this browser (ADR-0027).
 *
 * The access token, good for fifteen minutes, is kept in this tab's memory only. The refresh
 * token, good for thirty days and spent on use, is kept in local storage with whom it belongs
 * to, so that a reload or another tab stays signed in. A refresh spends the token the API
 * issued last, so the browser's tabs take turns (the Web Locks API): two tabs spending one
 * token would look to the API like a stolen copy, and it would end the session.
 */
import { ApiError, request } from "@/lib/api";

export type Role = "owner" | "accountant" | "client";

/** Who is signed in, in which organization, with which role. */
export interface Identity {
  user: { id: string; email: string };
  organization: { id: string; name: string };
  role: Role;
}

/** The API's answer to a sign-in, a registration or a refresh (`TokenResponse`). */
interface Tokens extends Identity {
  access_token: string;
  expires_in: number;
  refresh_token: string;
  refresh_expires_in: number;
}

/** An organization the visitor is a member of, as a sign-in that must choose lists them. */
export interface Membership {
  organization: { id: string; name: string };
  role: Role;
}

/** What local storage keeps of a session. */
interface Kept {
  refreshToken: string;
  refreshExpiresAt: number;
  identity: Identity;
}

export type Session =
  /** Not known yet: the page was rendered where there is no browser storage. */
  | { status: "unknown" }
  | { status: "signed-out" }
  | { status: "signed-in"; identity: Identity };

/** The request needs a session, and there is none any more, or none was started. */
export class SignedOutError extends ApiError {
  constructor() {
    super(401, "not signed in");
    this.name = "SignedOutError";
  }
}

export const STORAGE_KEY = "sef-kopilot.session";
export const REFRESH_LOCK = "sef-kopilot.refresh";
/** An access token is replaced this long before it expires, so that no request meets its end. */
export const EARLY_MS = 30_000;

const JSON_BODY = { "Content-Type": "application/json" };
const UNKNOWN: Session = { status: "unknown" };
const SIGNED_OUT: Session = { status: "signed-out" };

/** This tab's access token, and whose it is. */
let access: { token: string; expiresAt: number; identity: Identity } | null =
  null;
let renewing: Promise<string | null> | null = null;
/** Where the session is kept when the browser refuses local storage (a private window). */
let unstored: string | null = null;
/** What this tab last read from storage, so that an unchanged session is the same object. */
let snapshot: {
  raw: string | null;
  expiresAt: number | null;
  session: Session;
} = {
  raw: null,
  expiresAt: null,
  session: SIGNED_OUT,
};
const listeners = new Set<() => void>();

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return unstored;
  }
}

function writeRaw(raw: string | null): void {
  unstored = raw;
  try {
    if (raw === null) {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, raw);
    }
  } catch {
    // The session lives in this tab's memory alone.
  }
}

function parse(raw: string | null): Kept | null {
  if (raw === null) {
    return null;
  }
  try {
    const kept = JSON.parse(raw) as Partial<Kept>;
    return typeof kept.refreshToken === "string" &&
      typeof kept.refreshExpiresAt === "number" &&
      typeof kept.identity?.user?.id === "string"
      ? (kept as Kept)
      : null;
  } catch {
    return null;
  }
}

function notify(): void {
  for (const listener of listeners) {
    listener();
  }
}

/** The session as this tab knows it; the same object until it changes or expires. */
export function currentSession(): Session {
  const raw = readRaw();
  const expired =
    snapshot.expiresAt !== null && snapshot.expiresAt <= Date.now();
  if (raw !== snapshot.raw || expired) {
    const kept = parse(raw);
    const live = kept !== null && kept.refreshExpiresAt > Date.now();
    snapshot = {
      raw,
      expiresAt: live ? kept.refreshExpiresAt : null,
      session: live
        ? { status: "signed-in", identity: kept.identity }
        : SIGNED_OUT,
    };
  }
  return snapshot.session;
}

/** The session of a page rendered without a browser. */
export function serverSession(): Session {
  return UNKNOWN;
}

function sameVisitor(a: Identity, b: Identity): boolean {
  return a.user.id === b.user.id && a.organization.id === b.organization.id;
}

/** Another tab signed in, refreshed or signed out. */
function onStorage(event: StorageEvent): void {
  if (event.key !== STORAGE_KEY && event.key !== null) {
    return;
  }
  const now = currentSession();
  if (
    access !== null &&
    (now.status !== "signed-in" || !sameVisitor(access.identity, now.identity))
  ) {
    // This tab's access token belongs to a session that has ended here too.
    access = null;
  }
  notify();
}

/** Calls ``listener`` whenever the session changes, in this tab or in another. */
export function subscribe(listener: () => void): () => void {
  if (listeners.size === 0) {
    window.addEventListener("storage", onStorage);
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      window.removeEventListener("storage", onStorage);
    }
  };
}

function identityOf(tokens: Tokens): Identity {
  return {
    user: tokens.user,
    organization: tokens.organization,
    role: tokens.role,
  };
}

function adopt(tokens: Tokens): Identity {
  const now = Date.now();
  const identity = identityOf(tokens);
  access = {
    token: tokens.access_token,
    expiresAt: now + tokens.expires_in * 1000,
    identity,
  };
  const kept: Kept = {
    refreshToken: tokens.refresh_token,
    refreshExpiresAt: now + tokens.refresh_expires_in * 1000,
    identity,
  };
  writeRaw(JSON.stringify(kept));
  notify();
  return identity;
}

function forget(): void {
  access = null;
  writeRaw(null);
  notify();
}

/** One tab at a time, where the browser can say so; Safari has the Web Locks API since 15.4. */
async function oneTabAtATime<T>(work: () => Promise<T>): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks) {
    return await navigator.locks.request(REFRESH_LOCK, work);
  }
  return await work();
}

/** A new access token for the refresh token kept last, or null when the session has ended. */
function renew(): Promise<string | null> {
  return oneTabAtATime(async () => {
    // Read under the lock: another tab may have spent the token this one knew.
    const kept = parse(readRaw());
    if (kept === null || kept.refreshExpiresAt <= Date.now()) {
      if (kept !== null) {
        forget();
      }
      return null;
    }
    try {
      const tokens = await request<Tokens>("/auth/refresh", {
        method: "POST",
        headers: JSON_BODY,
        body: JSON.stringify({ refresh_token: kept.refreshToken }),
      });
      adopt(tokens);
      return tokens.access_token;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        // Spent, revoked or expired: the session has ended.
        forget();
        return null;
      }
      // The API could not be reached: the session is kept, and the next request tries again.
      throw error;
    }
  });
}

/**
 * An access token good for at least {@link EARLY_MS} more, or null when nobody is signed in.
 * Requests at the same moment share one refresh.
 */
export function accessToken(): Promise<string | null> {
  if (access !== null && access.expiresAt - EARLY_MS > Date.now()) {
    return Promise.resolve(access.token);
  }
  renewing ??= renew().finally(() => {
    renewing = null;
  });
  return renewing;
}

/**
 * The API's answer to a request in the visitor's name. A token the API refuses is replaced once
 * and the request sent again; with no session left, a {@link SignedOutError}.
 */
export async function authorized<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const send = (token: string) => {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return request<T>(path, { ...init, headers });
  };
  const token = await accessToken();
  if (token === null) {
    throw new SignedOutError();
  }
  try {
    return await send(token);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) {
      throw error;
    }
    if (access?.token === token) {
      access = null;
    }
    const renewed = await accessToken();
    if (renewed === null) {
      throw new SignedOutError();
    }
    return send(renewed);
  }
}

/**
 * Signs in. A member of several organizations names one in ``organizationId``; without it the
 * API answers 409 and {@link organizationsToChoose} lists them.
 */
export async function signIn(credentials: {
  email: string;
  password: string;
  organizationId?: string;
}): Promise<Identity> {
  const tokens = await request<Tokens>("/auth/login", {
    method: "POST",
    headers: JSON_BODY,
    body: JSON.stringify({
      email: credentials.email,
      password: credentials.password,
      organization_id: credentials.organizationId ?? null,
    }),
  });
  return adopt(tokens);
}

/** Creates an account with its organization, and signs in. */
export async function register(account: {
  email: string;
  password: string;
  organizationName: string;
}): Promise<Identity> {
  const tokens = await request<Tokens>("/auth/register", {
    method: "POST",
    headers: JSON_BODY,
    body: JSON.stringify({
      email: account.email,
      password: account.password,
      organization_name: account.organizationName,
    }),
  });
  return adopt(tokens);
}

/** The organizations a sign-in must choose from, when its answer asks for one. */
export function organizationsToChoose(error: unknown): Membership[] | null {
  if (!(error instanceof ApiError) || error.status !== 409) {
    return null;
  }
  const body = error.body as { organizations?: unknown } | null;
  return Array.isArray(body?.organizations)
    ? (body.organizations as Membership[])
    : null;
}

/**
 * Signs out: this browser forgets the session at once, and the API revokes it. If the API
 * cannot be reached, its tokens expire unused.
 */
export async function signOut(): Promise<void> {
  const kept = parse(readRaw());
  forget();
  if (kept === null) {
    return;
  }
  try {
    await request<void>("/auth/logout", {
      method: "POST",
      headers: JSON_BODY,
      body: JSON.stringify({ refresh_token: kept.refreshToken }),
    });
  } catch {
    // Forgotten here already; nothing else to do.
  }
}
