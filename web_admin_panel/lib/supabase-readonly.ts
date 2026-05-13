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
  stock: Array<{ name: string; branch: string; stock: number; price: number }>;
  byBranch: Array<{ branch: string; todayTotal: number; saleCount: number; customerCount: number; productCount: number; userCount: number }>;
};

const TABLES = ["users", "customers", "products", "sales"] as const;
const BRANCH_KEYS = ["kasa_id", "profile_id", "branch_id"] as const;
const EXTRA_BRANCH_KEYS = ["cashier_id", "device_id", "user_id", "cashier", "kasa", "branch", "profile"] as const;

function env(name: string): string {
  return (process.env[name] || "").trim();
}

function keyOf(row: Row, key: string): string | undefined {
  if (Object.prototype.hasOwnProperty.call(row, key)) return key;
  const wanted = key.toLowerCase();
  return Object.keys(row).find((existing) => existing.toLowerCase() === wanted);
}

function valueOf(row: Row, key: string): unknown {
  const actual = keyOf(row, key);
  return actual ? row[actual] : undefined;
}

function numberValue(value: unknown): number {
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

function first(row: Row, keys: readonly string[], fallback = ""): string {
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

function normalizeBranch(value: string): string {
  return value.trim().toLowerCase();
}

export function branchOf(row: Row): string {
  return first(row, BRANCH_KEYS);
}

function branchKey(row: Row): string {
  return normalizeBranch(branchOf(row));
}

function fallbackBranch(row: Row): string {
  return branchOf(row) || first(row, EXTRA_BRANCH_KEYS, "genel-kasa");
}

function saleTotal(row: Row): number {
  return firstNumber(row, ["total", "total_amount", "grand_total", "amount", "net_total", "price", "tutar", "toplam", "total_price"]);
}

function balance(row: Row): number {
  return firstNumber(row, ["balance", "current_balance", "bakiye", "debt_balance", "remaining_balance"]);
}

function stock(row: Row): number {
  return firstNumber(row, ["stock", "stock_quantity", "quantity", "qty", "stok", "current_stock"]);
}

function price(row: Row): number {
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

function isActive(row: Row): boolean {
  const archived = valueOf(row, "archived");
  const is_active = valueOf(row, "is_active");
  return archived !== true && archived !== 1 && is_active !== false && is_active !== 0;
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

async function select(table: string): Promise<Row[]> {
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
  const usersAll = usersResult.rows.filter(isActive);
  const customersAll = customersResult.rows;
  const productsAll = productsResult.rows;
  const salesAll = salesResult.rows;

  const users = filterBranch(usersAll, selectedBranch);
  const customers = filterBranch(customersAll, selectedBranch);
  const products = filterBranch(productsAll, selectedBranch);
  const sales = filterBranch(salesAll, selectedBranch);
  const today = todayKey();
  const todaySales = sales.filter((sale) => dateKey(saleDateRaw(sale)) === today);
  const branches = Array.from(new Set([
    ...usersAll.map(fallbackBranch),
    ...customersAll.map(fallbackBranch),
    ...productsAll.map(fallbackBranch),
    ...salesAll.map(fallbackBranch)
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
    selectedBranch,
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
      name: first(product, ["name", "product_name", "title", "urun_adi"], "-"),
      branch: fallbackBranch(product),
      stock: stock(product),
      price: price(product)
    })).sort((a, b) => a.name.localeCompare(b.name, "tr")).slice(0, 200),
    byBranch: Array.from(byBranchMap.values())
      .filter((item) => !selectedBranch || normalizeBranch(item.branch) === normalizeBranch(selectedBranch))
      .sort((a, b) => a.branch.localeCompare(b.branch, "tr"))
  };
}
