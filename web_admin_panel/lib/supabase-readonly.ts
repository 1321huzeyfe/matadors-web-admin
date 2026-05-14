export type Row = Record<string, unknown>;

export type PanelData = {
  errors: string[];
  branches: string[];
  selectedBranch: string;
    summary: {
      todayTotal: number;
      saleCount: number;
      customerCount: number;
      productCount: number;
      userCount: number;
      totalBalance: number;
      totalStock: number;
      updatedAt: string;
    };
  users: Row[];
  customers: Row[];
  products: Row[];
  sales: Row[];
  balances: Array<{ name: string; branch: string; balance: number }>;
  stock: Array<{ id: string; name: string; category: string; branch: string; stock: number; price: number }>;
  byBranch: Array<{ branch: string; todayTotal: number; saleCount: number; customerCount: number; productCount: number; userCount: number }>;
};

const TABLES = ["users", "customers", "products", "sales"] as const;
const BRANCH_KEYS = ["kasa_id", "profile_id", "branch_id"] as const;
const EXTRA_BRANCH_KEYS = ["cashier_id", "device_id", "user_id", "cashier", "kasa", "branch", "profile"] as const;

export function env(name: string): string {
  return (process.env[name] || "").trim();
}

function keyOf(row: Row, key: string): string | undefined {
  if (Object.prototype.hasOwnProperty.call(row, key)) return key;
  const wanted = key.toLowerCase();
  return Object.keys(row).find((existing) => existing.toLowerCase() === wanted);
}

export function valueOf(row: Row, key: string): unknown {
  const actual = keyOf(row, key);
  return actual ? row[actual] : undefined;
}

export function numberValue(value: unknown): number {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const clean = String(value ?? "")
    .replace(/\s/g, "")
    .replace(/[₺TLtl]/g, "")
    .replace(/\.(?=\d{3}(\D|$))/g, "")
    .replace(",", ".");
  const number = Number(clean || 0);
  return Number.isFinite(number) ? number : 0;
}

function stringValue(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

export function first(row: Row, keys: readonly string[], fallback = ""): string {
  for (const key of keys) {
    const value = stringValue(valueOf(row, key)).trim();
    if (value) return value;
  }
  return fallback;
}

function firstNumber(row: Row, keys: readonly string[]): number {
  for (const key of keys) {
    const value = valueOf(row, key);
    if (value !== undefined && value !== null && String(value).trim() !== "") return numberValue(value);
  }
  return 0;
}

export function normalizeBranch(value: string): string {
  return value.trim().toLowerCase();
}

export function branchOf(row: Row): string {
  return first(row, BRANCH_KEYS);
}

function branchKey(row: Row): string {
  return normalizeBranch(branchOf(row));
}

export function fallbackBranch(row: Row): string {
  return branchOf(row) || first(row, EXTRA_BRANCH_KEYS, "genel-kasa");
}

function saleTotal(row: Row): number {
  return firstNumber(row, ["total", "total_amount", "grand_total", "amount", "net_total", "price", "tutar", "toplam", "total_price"]);
}

export function balance(row: Row): number {
  return firstNumber(row, ["balance", "current_balance", "bakiye", "debt_balance", "remaining_balance"]);
}

export function stock(row: Row): number {
  return firstNumber(row, ["stock", "stock_quantity", "quantity", "qty", "stok", "current_stock"]);
}

export function price(row: Row): number {
  return firstNumber(row, ["price", "sale_price", "unit_price", "fiyat", "selling_price"]);
}

function saleDateRaw(row: Row): string {
  return first(row, ["created_at", "sale_date", "date", "createdAt", "timestamp", "sold_at", "datetime", "tarih"]);
}

function dateKey(value: string): string {
  if (!value) return "";
  const direct = value.match(/^(\d{4}-\d{2}-\d{2})/);
  if (direct) return direct[1];
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10);
  return parsed.toISOString().slice(0, 10);
}

function todayKey(): string {
  return new Date().toISOString().slice(0, 10);
}

export function isActive(row: Row): boolean {
  const archived = valueOf(row, "archived");
  const is_active = valueOf(row, "is_active");
  return archived !== true && archived !== 1 && is_active !== false && is_active !== 0;
}

function isAdminLikeBranch(branch: string): boolean {
  const clean = normalizeBranch(branch);
  if (clean.includes("admin") || clean.includes("genel") || clean.includes("manager")) return true;
  return !clean || clean === "admin" || clean === "manager" || clean === "genel-kasa" || clean === "general" || clean === "yonetici" || clean === "yönetici";
}

function isCashierUser(row: Row): boolean {
  const role = first(row, ["user_type", "role", "type"], "").toLowerCase();
  return isActive(row) && (role === "cashier" || role === "kasa");
}

function actorId(row: Row): string {
  return first(row, ["cashier_id", "user_id"], "");
}

function userId(row: Row): string {
  return first(row, ["id", "cashier_id", "user_id"], "");
}

function realScope(users: Row[], dataRows: Row[]) {
  const cashierIds = new Set(users.filter(isCashierUser).map(userId).filter(Boolean));
  const adminIds = new Set(users.filter((row) => !isCashierUser(row)).map(userId).filter(Boolean));
  const branches = new Set<string>();

  for (const row of users.filter(isCashierUser)) {
    const branch = fallbackBranch(row).trim();
    if (branch && !isAdminLikeBranch(branch)) branches.add(branch);
  }

  for (const row of dataRows.filter(isActive)) {
    const branch = fallbackBranch(row).trim();
    const id = actorId(row);
    if (!branch || isAdminLikeBranch(branch)) continue;
    if (id && adminIds.has(id)) continue;
    if (id && cashierIds.size > 0 && !cashierIds.has(id) && /^\d+$/.test(branch)) continue;
    branches.add(branch);
  }

  return { branches, cashierIds, adminIds };
}

function isRealBranchRow(row: Row, scope: ReturnType<typeof realScope>): boolean {
  const branch = fallbackBranch(row).trim();
  const id = actorId(row);
  if (!branch || isAdminLikeBranch(branch)) return false;
  if (id && scope.adminIds.has(id)) return false;
  if (scope.branches.has(branch)) return true;
  return Boolean(id && scope.cashierIds.has(id));
}

function filterRealBranches(rows: Row[], scope: ReturnType<typeof realScope>): Row[] {
  return rows.filter((row) => isActive(row) && isRealBranchRow(row, scope));
}

function filterBranch(rows: Row[], selectedBranch: string): Row[] {
  const selected = normalizeBranch(selectedBranch);
  if (!selected) return rows;
  return rows.filter((row) => branchKey(row) === selected || normalizeBranch(fallbackBranch(row)) === selected);
}

function ensureBranch(map: Map<string, PanelData["byBranch"][number]>, branch: string) {
  const key = branch || "genel-kasa";
  if (!map.has(key)) {
    map.set(key, { branch: key, todayTotal: 0, saleCount: 0, customerCount: 0, productCount: 0, userCount: 0 });
  }
  return map.get(key)!;
}

export async function select(table: string): Promise<Row[]> {
  const url = env("SUPABASE_URL").replace(/\/+$/, "");
  const key = env("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) throw new Error("SUPABASE_URL veya SUPABASE_SERVICE_ROLE_KEY eksik.");

  const response = await fetch(`${url}/rest/v1/${table}?select=*`, {
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      Accept: "application/json"
    },
    cache: "no-store"
  });

  const text = await response.text();
  if (!response.ok) throw new Error(`${table}: ${response.status} ${text}`);
  return text ? JSON.parse(text) : [];
}

async function safeSelect(table: string): Promise<{ rows: Row[]; error: string }> {
  try {
    return { rows: await select(table), error: "" };
  } catch (error) {
    console.log(`[panel] Supabase ${table} okunamadı:`, error);
    return { rows: [], error: "Veri alınamadı. Supabase bağlantısını kontrol edin." };
  }
}

export async function loadPanelData(selectedBranch = ""): Promise<PanelData> {
  const [usersResult, customersResult, productsResult, salesResult] = await Promise.all(TABLES.map(safeSelect));
  const errors = Array.from(new Set(
    [usersResult, customersResult, productsResult, salesResult].map((result) => result.error).filter(Boolean)
  ));
  const usersAllRaw = usersResult.rows.filter(isActive);
  const scope = realScope(usersAllRaw, [...customersResult.rows, ...productsResult.rows, ...salesResult.rows]);
  const realBranches = scope.branches;
  const selectedIsReal = !selectedBranch || realBranches.has(selectedBranch);
  const effectiveBranch = selectedIsReal ? selectedBranch : "";
  const usersAll = usersAllRaw.filter((row) => isRealBranchRow(row, scope));
  const customersAll = filterRealBranches(customersResult.rows, scope);
  const productsAll = filterRealBranches(productsResult.rows, scope);
  const salesAll = filterRealBranches(salesResult.rows, scope);

  const users = filterBranch(usersAll, effectiveBranch);
  const customers = filterBranch(customersAll, effectiveBranch);
  const products = filterBranch(productsAll, effectiveBranch);
  const sales = filterBranch(salesAll, effectiveBranch);
  const today = todayKey();
  const todaySales = sales.filter((sale) => dateKey(saleDateRaw(sale)) === today);
  const branches = Array.from(new Set([
    ...usersAll.map(fallbackBranch),
    ...Array.from(realBranches)
  ].map((branch) => branch.trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b, "tr"));

  const byBranchMap = new Map<string, PanelData["byBranch"][number]>();
  for (const branch of branches) ensureBranch(byBranchMap, branch);
  for (const user of usersAll) ensureBranch(byBranchMap, fallbackBranch(user)).userCount += 1;
  for (const customer of customersAll) ensureBranch(byBranchMap, fallbackBranch(customer)).customerCount += 1;
  for (const product of productsAll) ensureBranch(byBranchMap, fallbackBranch(product)).productCount += 1;
  for (const sale of salesAll.filter((item) => dateKey(saleDateRaw(item)) === today)) {
    const item = ensureBranch(byBranchMap, fallbackBranch(sale));
    item.saleCount += 1;
    item.todayTotal += saleTotal(sale);
  }

  return {
    errors,
    branches,
    selectedBranch: effectiveBranch,
    summary: {
      todayTotal: todaySales.reduce((total, sale) => total + saleTotal(sale), 0),
      saleCount: sales.length,
      customerCount: customers.length,
      productCount: products.length,
      userCount: users.length,
      totalBalance: customers.reduce((total, customer) => total + balance(customer), 0),
      totalStock: products.reduce((total, product) => total + stock(product), 0),
      updatedAt: new Date().toISOString()
    },
    users,
    customers,
    products,
    sales: sales.sort((a, b) => saleDateRaw(b).localeCompare(saleDateRaw(a))).slice(0, 100),
    balances: customers.map((customer) => ({
      name: first(customer, ["name", "full_name", "customer_name", "ad_soyad"], "-"),
      branch: fallbackBranch(customer),
      balance: balance(customer)
    })).sort((a, b) => a.name.localeCompare(b.name, "tr")).slice(0, 200),
    stock: products.map((product) => ({
      id: first(product, ["id"], ""),
      name: first(product, ["name", "product_name", "title", "urun_adi"], "-"),
      category: first(product, ["category", "kategori"], ""),
      branch: fallbackBranch(product),
      stock: stock(product),
      price: price(product)
    })).sort((a, b) => a.name.localeCompare(b.name, "tr")).slice(0, 200),
    byBranch: Array.from(byBranchMap.values())
      .filter((item) => !effectiveBranch || normalizeBranch(item.branch) === normalizeBranch(effectiveBranch))
      .sort((a, b) => a.branch.localeCompare(b.branch, "tr"))
  };
}

export async function loadWritableBranches(): Promise<Array<{ branch: string; cashierId: string; label: string }>> {
  const users = (await select("users")).filter(isCashierUser);
  const rows = users
    .map((user) => {
      const branch = fallbackBranch(user);
      return {
        branch,
        cashierId: first(user, ["id", "cashier_id"], ""),
        label: first(user, ["full_name", "name", "username"], branch)
      };
    })
    .filter((row) => row.branch && row.cashierId && !isAdminLikeBranch(row.branch));
  return rows.sort((a, b) => a.label.localeCompare(b.label, "tr"));
}

export async function restRequest(table: string, init: RequestInit & { query?: string } = {}) {
  const url = env("SUPABASE_URL").replace(/\/+$/, "");
  const key = env("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) throw new Error("SUPABASE_URL veya SUPABASE_SERVICE_ROLE_KEY eksik.");
  const response = await fetch(`${url}/rest/v1/${table}${init.query || ""}`, {
    ...init,
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
      ...(init.headers || {})
    },
    cache: "no-store"
  });
  const text = await response.text();
  if (!response.ok) throw new Error(`${table}: ${response.status} ${text}`);
  return text ? JSON.parse(text) : [];
}
