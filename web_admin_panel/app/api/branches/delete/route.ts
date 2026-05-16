import { NextRequest, NextResponse } from "next/server";
import { isValidSessionToken, SESSION_COOKIE } from "../../../../lib/auth";
import { branchValueFromKey, isSystemBranchValue, loadPanelData, restRequest, select } from "../../../../lib/supabase-readonly";
import type { Row } from "../../../../lib/supabase-readonly";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const DATA_BRANCH_FIELDS = ["branch_id", "kasa_id", "profile_id"] as const;
const USER_BRANCH_FIELDS = ["branch_id", "kasa_id", "profile_id", "username"] as const;

function bad(message: string, status = 400) {
  return NextResponse.json({ ok: false, error: message }, { status });
}

function cleanBranchValue(value: unknown): string {
  const clean = String(value ?? "").trim();
  const lowered = clean.toLowerCase();
  if (!clean || lowered === "null" || lowered === "undefined") return "";
  const compact = lowered.replace(/\s+/g, "");
  return compact.startsWith("branch_id:") ? compact.slice("branch_id:".length) : compact;
}

function canonicalBranchKey(value: unknown): string {
  const clean = cleanBranchValue(value);
  return clean ? `branch_id:${clean}` : "";
}

function rowMatchesBranch(row: Row, branchKey: string, fields: readonly string[]) {
  return fields.some((field) => canonicalBranchKey(row[field]) === branchKey);
}

function idValue(row: Row): string {
  return String(row.id ?? "").trim();
}

function deleteQuery(ids: string[]) {
  return `?id=in.(${ids.map((id) => encodeURIComponent(id)).join(",")})`;
}

async function deleteRows(table: string, ids: string[]) {
  let deleted = 0;
  for (let index = 0; index < ids.length; index += 100) {
    const chunk = ids.slice(index, index + 100);
    if (chunk.length === 0) continue;
    const rows = await restRequest(table, {
      method: "DELETE",
      query: deleteQuery(chunk)
    });
    deleted += Array.isArray(rows) ? rows.length : chunk.length;
  }
  return deleted;
}

export async function POST(request: NextRequest) {
  if (!isValidSessionToken(request.cookies.get(SESSION_COOKIE)?.value)) {
    return bad("Yetkisiz erisim.", 401);
  }

  try {
    const body = await request.json();
    const branchKey = String(body.branchKey || "").trim().toLowerCase();
    const branchLabel = String(body.branchLabel || "").trim();
    const confirmation = String(body.confirmation || "");
    const branchValue = branchValueFromKey(branchKey);

    if (!branchKey.startsWith("branch_id:") || !branchValue) return bad("Gecersiz kasa anahtari.");
    if (!branchLabel) return bad("Kasa adi eksik.");
    if (confirmation !== branchLabel) return bad("Kasa adi onayi eslesmiyor.");
    if (isSystemBranchValue(branchValue) || isSystemBranchValue(branchLabel)) {
      return bad("Sistem/test kasalari kalici olarak silinemez.", 403);
    }

    const panelData = await loadPanelData("");
    const visibleBranch = panelData.branches.find((branch) => branch.key === branchKey && branch.label === branchLabel);
    if (!visibleBranch) {
      return bad("Sadece gorunen aktif kasalar silinebilir.", 403);
    }

    const [salesRows, productsRows, customersRows, usersRows] = await Promise.all([
      select("sales"),
      select("products"),
      select("customers"),
      select("users")
    ]);

    const targets = {
      sales: salesRows.filter((row) => rowMatchesBranch(row, branchKey, DATA_BRANCH_FIELDS)),
      products: productsRows.filter((row) => rowMatchesBranch(row, branchKey, DATA_BRANCH_FIELDS)),
      customers: customersRows.filter((row) => rowMatchesBranch(row, branchKey, DATA_BRANCH_FIELDS)),
      users: usersRows.filter((row) => rowMatchesBranch(row, branchKey, USER_BRANCH_FIELDS))
    };
    const ids = {
      sales: targets.sales.map(idValue).filter(Boolean),
      products: targets.products.map(idValue).filter(Boolean),
      customers: targets.customers.map(idValue).filter(Boolean),
      users: targets.users.map(idValue).filter(Boolean)
    };

    for (const [table, rows] of Object.entries(targets)) {
      if (rows.length !== ids[table as keyof typeof ids].length) {
        return bad(`${table} icinde id olmayan kayit var; silme durduruldu.`);
      }
    }

    const before = {
      sales: ids.sales.length,
      products: ids.products.length,
      customers: ids.customers.length,
      users: ids.users.length
    };
    const deleted = {
      sales: await deleteRows("sales", ids.sales),
      products: await deleteRows("products", ids.products),
      customers: await deleteRows("customers", ids.customers),
      users: await deleteRows("users", ids.users)
    };

    return NextResponse.json({ ok: true, branchKey, branchLabel, before, deleted }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.log("[branches/delete] Kasa silinemedi:", error);
    return bad(error instanceof Error ? error.message : "Kasa silinemedi.");
  }
}
