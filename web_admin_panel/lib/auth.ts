import crypto from "crypto";
import { cookies } from "next/headers";

export const SESSION_COOKIE = "matadors_admin_session";
const SESSION_MAX_AGE_SECONDS = 12 * 60 * 60;

function secret() {
  return process.env.ADMIN_SESSION_SECRET || process.env.ADMIN_PANEL_PASSWORD || "";
}

function sign(value: string) {
  return crypto.createHmac("sha256", secret()).update(value).digest("hex");
}

function safeEqual(a: string, b: string) {
  const left = Buffer.from(a || "");
  const right = Buffer.from(b || "");
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

function encodePayload(payload: Record<string, unknown>) {
  return Buffer.from(JSON.stringify(payload)).toString("base64url");
}

function decodePayload(body: string) {
  try {
    return JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as { exp?: number };
  } catch (_error) {
    return {};
  }
}

export function createSessionToken() {
  const body = encodePayload({ sub: "admin", exp: Date.now() + SESSION_MAX_AGE_SECONDS * 1000 });
  return `${body}.${sign(body)}`;
}

export function isValidSessionToken(token?: string) {
  if (!secret() || !token || !token.includes(".")) return false;
  const [body, signature] = token.split(".");
  if (!safeEqual(signature || "", sign(body || ""))) return false;
  const payload = decodePayload(body || "");
  return typeof payload.exp === "number" && payload.exp > Date.now();
}

export function isPasswordValid(password: string) {
  const expected = process.env.ADMIN_PANEL_PASSWORD || "";
  return Boolean(expected) && safeEqual(password, expected);
}

export function isPageAuthenticated() {
  return isValidSessionToken(cookies().get(SESSION_COOKIE)?.value);
}

export function sessionCookieOptions() {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS
  };
}
