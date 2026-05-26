import { NextRequest, NextResponse } from "next/server";
import { isValidSessionToken, SESSION_COOKIE } from "../../../../lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (!isValidSessionToken(request.cookies.get(SESSION_COOKIE)?.value)) {
    return NextResponse.json({ ok: false, error: "Yetkisiz erişim." }, { status: 401 });
  }

  return NextResponse.json(
    {
      ok: false,
      error: "Web admin panel salt-okunur modda çalışır. Kasa silme ve pasifleştirme işlemleri masaüstü uygulamadan yapılır."
    },
    { status: 405, headers: { "Cache-Control": "no-store" } }
  );
}
