import { NextRequest, NextResponse } from "next/server";
import { createSessionToken, isPasswordValid, SESSION_COOKIE, sessionCookieOptions } from "../../../lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const password = String(body.password || "");
  if (!isPasswordValid(password)) {
    return NextResponse.json({ ok: false, error: "Sifre hatali." }, { status: 401 });
  }
  const response = NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
  response.cookies.set(SESSION_COOKIE, createSessionToken(), sessionCookieOptions());
  return response;
}
