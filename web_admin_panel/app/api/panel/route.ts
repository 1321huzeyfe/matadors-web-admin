import { NextRequest, NextResponse } from "next/server";
import { isValidSessionToken, SESSION_COOKIE } from "../../../lib/auth";
import { loadPanelData } from "../../../lib/supabase-readonly";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  if (!isValidSessionToken(request.cookies.get(SESSION_COOKIE)?.value)) {
    return NextResponse.json({ ok: false, error: "Yetkisiz erisim." }, { status: 401 });
  }
  try {
    const branch = request.nextUrl.searchParams.get("branch") || "";
    const data = await loadPanelData(branch);
    return NextResponse.json(data, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.log("[panel] Panel verisi hazırlanamadı:", error);
    return NextResponse.json({
      errors: ["Veri alınamadı. Supabase bağlantısını kontrol edin."],
      branches: [],
      selectedBranch: "",
      summary: {
        todayTotal: 0,
        saleCount: 0,
        customerCount: 0,
        productCount: 0,
        userCount: 0,
        totalBalance: 0,
        totalStock: 0,
        updatedAt: new Date().toISOString()
      },
      users: [],
      customers: [],
      products: [],
      sales: [],
      balances: [],
      stock: [],
      byBranch: [],
      debug: {
        apiCustomers: 0,
        apiProducts: 0,
        apiSales: 0,
        filteredCustomers: 0,
        filteredProducts: 0
      }
    }, { headers: { "Cache-Control": "no-store" } });
  }
}
