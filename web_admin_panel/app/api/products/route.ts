import { NextRequest, NextResponse } from "next/server";
import { isValidSessionToken, SESSION_COOKIE } from "../../../lib/auth";
import { fallbackBranch, first, loadWritableBranches, normalizeBranch, restRequest, select, stock, Row } from "../../../lib/supabase-readonly";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function bad(message: string, status = 400) {
  return NextResponse.json({ ok: false, error: message }, { status });
}

function sameBranch(a: string, b: string) {
  return normalizeBranch(a) === normalizeBranch(b);
}

async function requireWritableBranch(branch: string) {
  const branches = await loadWritableBranches();
  const match = branches.find((item) => sameBranch(item.branch, branch));
  if (!match) throw new Error("Sadece gerçek kasa seçiliyken ürün işlemi yapılabilir.");
  return match;
}

async function loadProduct(productId: string, branch: string): Promise<Row> {
  const rows = await select("products");
  const product = rows.find((row) => String(first(row, ["id"], "")) === productId && sameBranch(fallbackBranch(row), branch));
  if (!product) throw new Error("Ürün bulunamadı veya seçili kasaya ait değil.");
  return product;
}

export async function POST(request: NextRequest) {
  if (!isValidSessionToken(request.cookies.get(SESSION_COOKIE)?.value)) {
    return bad("Yetkisiz erişim.", 401);
  }

  try {
    const body = await request.json();
    const action = String(body.action || "").trim();
    const branch = String(body.branch || "").trim();
    const writable = await requireWritableBranch(branch);

    if (action === "create") {
      const name = String(body.name || "").trim();
      const category = String(body.category || "").trim();
      const nextPrice = Number(body.price || 0);
      const nextStock = Number(body.stock || 0);
      if (!name) return bad("Ürün adı zorunlu.");
      if (!category) return bad("Kategori zorunlu.");
      if (!Number.isFinite(nextPrice) || nextPrice < 0) return bad("Fiyat geçersiz.");
      if (!Number.isFinite(nextStock) || nextStock < 0) return bad("Stok geçersiz.");

      await restRequest("products", {
        method: "POST",
        body: JSON.stringify({
          name,
          category,
          price: nextPrice,
          stock: nextStock,
          active: 1,
          archived: 0,
          is_active: 1,
          cashier_id: Number(writable.cashierId),
          branch_id: writable.branch,
          profile_id: writable.branch,
          kasa_id: writable.branch,
          created_at: new Date().toISOString()
        })
      });
      return NextResponse.json({ ok: true });
    }

    const productId = String(body.productId || "").trim();
    if (!productId) return bad("Ürün seçimi zorunlu.");
    const product = await loadProduct(productId, writable.branch);

    if (action === "update") {
      const nextName = String(body.name || first(product, ["name", "product_name", "title"], "")).trim();
      const nextCategory = String(body.category || first(product, ["category", "kategori"], "")).trim();
      const nextPrice = Number(body.price);
      if (!nextName) return bad("Ürün adı zorunlu.");
      if (!nextCategory) return bad("Kategori zorunlu.");
      if (!Number.isFinite(nextPrice) || nextPrice < 0) return bad("Fiyat geçersiz.");
      await restRequest("products", {
        method: "PATCH",
        query: `?id=eq.${encodeURIComponent(productId)}`,
        body: JSON.stringify({ name: nextName, category: nextCategory, price: nextPrice })
      });
      return NextResponse.json({ ok: true });
    }

    if (action === "adjust") {
      const delta = Number(body.delta || 0);
      if (!Number.isFinite(delta) || delta === 0) return bad("Stok değişimi geçersiz.");
      const nextStock = Math.max(0, stock(product) + delta);
      await restRequest("products", {
        method: "PATCH",
        query: `?id=eq.${encodeURIComponent(productId)}`,
        body: JSON.stringify({ stock: nextStock })
      });
      return NextResponse.json({ ok: true, stock: nextStock });
    }

    if (action === "deactivate") {
      await restRequest("products", {
        method: "PATCH",
        query: `?id=eq.${encodeURIComponent(productId)}`,
        body: JSON.stringify({ active: 0, archived: 1, is_active: 0 })
      });
      return NextResponse.json({ ok: true });
    }

    return bad("Bilinmeyen işlem.");
  } catch (error) {
    console.log("[products] Ürün işlemi yapılamadı:", error);
    return bad(error instanceof Error ? error.message : "Ürün işlemi yapılamadı.");
  }
}
