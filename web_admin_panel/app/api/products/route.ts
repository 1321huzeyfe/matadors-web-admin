import { NextRequest, NextResponse } from "next/server";
import { isValidSessionToken, SESSION_COOKIE } from "../../../lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type ProductPayload = {
  id?: unknown;
  name?: unknown;
  category?: unknown;
  stock?: unknown;
  price?: unknown;
  branchKey?: unknown;
};

const PRODUCT_SELECT = "id,branch_id,profile_id,kasa_id";

function json(body: Record<string, unknown>, status = 200) {
  return NextResponse.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

function authorized(request: NextRequest) {
  return isValidSessionToken(request.cookies.get(SESSION_COOKIE)?.value);
}

function env(name: string) {
  return (process.env[name] || "").trim();
}

function normalizeBranch(value: unknown) {
  return String(value || "")
    .trim()
    .replace(/^branch_id:/i, "")
    .toLowerCase();
}

function parsePayload(body: ProductPayload) {
  const name = String(body.name || "").trim();
  const category = String(body.category || "").trim();
  const branchId = normalizeBranch(body.branchKey);
  const stock = Number(String(body.stock ?? "0").replace(",", "."));
  const price = Number(String(body.price ?? "0").replace(",", "."));

  if (!branchId) return { error: "Ürün işlemi için kasa/branch seçimi zorunludur." };
  if (!name) return { error: "Ürün adı boş olamaz." };
  if (!Number.isFinite(stock) || stock < 0) return { error: "Stok 0 veya daha büyük bir sayı olmalıdır." };
  if (!Number.isFinite(price) || price < 0) return { error: "Fiyat 0 veya daha büyük bir sayı olmalıdır." };

  return { name, category, branchId, stock, price };
}

async function supabase(path: string, init: RequestInit = {}) {
  const url = env("SUPABASE_URL").replace(/\/+$/, "");
  const serviceKey = env("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !serviceKey) {
    throw new Error("Supabase server-side yazma anahtarı yapılandırılmamış.");
  }

  const response = await fetch(`${url}/rest/v1/${path}`, {
    ...init,
    headers: {
      apikey: serviceKey,
      Authorization: `Bearer ${serviceKey}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
      ...(init.headers || {})
    },
    cache: "no-store"
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message = data?.message || data?.error || "Supabase işlemi tamamlanamadı.";
    throw new Error(String(message));
  }
  return data;
}

function rowMatchesBranch(row: Record<string, unknown>, branchId: string) {
  return ["branch_id", "profile_id", "kasa_id"].some((key) => normalizeBranch(row[key]) === branchId);
}

export async function POST(request: NextRequest) {
  if (!authorized(request)) return json({ success: false, error: "Yetkisiz erişim." }, 401);

  try {
    const parsed = parsePayload(await request.json().catch(() => ({})));
    if ("error" in parsed) return json({ success: false, error: parsed.error }, 400);

    const now = new Date().toISOString();
    const payload = {
      name: parsed.name,
      category: parsed.category,
      stock: parsed.stock,
      price: parsed.price,
      branch_id: parsed.branchId,
      profile_id: parsed.branchId,
      kasa_id: parsed.branchId,
      is_active: true,
      archived: false,
      created_at: now,
      updated_at: now
    };

    const product = await supabase("products", { method: "POST", body: JSON.stringify(payload) });
    return json({ success: true, product });
  } catch (error) {
    return json({ success: false, error: error instanceof Error ? error.message : "Ürün eklenemedi." }, 500);
  }
}

export async function PATCH(request: NextRequest) {
  if (!authorized(request)) return json({ success: false, error: "Yetkisiz erişim." }, 401);

  try {
    const body = await request.json().catch(() => ({})) as ProductPayload;
    const id = String(body.id || "").trim();
    if (!id) return json({ success: false, error: "Güncellenecek ürün kimliği eksik." }, 400);

    const parsed = parsePayload(body);
    if ("error" in parsed) return json({ success: false, error: parsed.error }, 400);

    const encodedId = encodeURIComponent(id);
    const existing = await supabase(`products?select=${PRODUCT_SELECT}&id=eq.${encodedId}&limit=1`, {
      method: "GET"
    }) as Record<string, unknown>[];

    if (!existing?.[0]) return json({ success: false, error: "Ürün bulunamadı." }, 404);
    if (!rowMatchesBranch(existing[0], parsed.branchId)) {
      return json({ success: false, error: "Ürün seçili kasa/branch kapsamında değil." }, 409);
    }

    const payload = {
      name: parsed.name,
      category: parsed.category,
      stock: parsed.stock,
      price: parsed.price,
      updated_at: new Date().toISOString()
    };
    const product = await supabase(`products?id=eq.${encodedId}`, { method: "PATCH", body: JSON.stringify(payload) });
    return json({ success: true, product });
  } catch (error) {
    return json({ success: false, error: error instanceof Error ? error.message : "Ürün güncellenemedi." }, 500);
  }
}

export async function PUT() {
  return json({ success: false, error: "PUT desteklenmiyor. Ürün güncelleme için PATCH kullanın." }, 405);
}

export async function DELETE() {
  return json({ success: false, error: "Ürün silme web panelden desteklenmez." }, 405);
}
