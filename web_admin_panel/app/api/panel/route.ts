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
      unmatchedBalances: [],
      unmatchedStock: [],
      byBranch: [],
      debug: {
        buildVersion: "branch-filter-debug-v6",
        dropdownBranches: [],
        warning: "Aktif kasa bulunamadı, users tablosundaki cashier kayıtlarını kontrol edin.",
        activeBranchKeys: [],
        blockedBranchKeys: [],
        inactiveBranchKeys: [],
        sampleCustomerBranchKeys: [],
        sampleProductBranchKeys: [],
        rawUsersCount: 0,
        activeUsersCount: 0,
        cashierCandidates: [],
        rejectedCashiers: [],
        apiCustomers: 0,
        apiProducts: 0,
        apiSales: 0,
        filteredCustomers: 0,
        filteredProducts: 0,
        selectedBranch: "",
        selectedKey: "ALL",
        customersBefore: 0,
        customersAfter: 0,
        productsBefore: 0,
        productsAfter: 0,
        unmatchedCustomers: 0,
        unmatchedProducts: 0
      }
    }, { headers: { "Cache-Control": "no-store" } });
  }
}
