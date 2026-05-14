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
  debug: {
    apiCustomers: number;
    apiProducts: number;
    apiSales: number;
    filteredCustomers: number;
    filteredProducts: number;
    selectedBranch: string;
    matchedAliases: number;
  };
};

const TABLES = ["users", "customers", "products", "sales"] as const;
const BRANCH_KEYS = ["kasa_id", "profile_id", "branch_id"] as const;
const EXTRA_BRANCH_KEYS = ["cashier_id", "device_id", "user_id", "cashier", "cashier_name", "kasa", "branch", "profile"] as const;
type BranchGroup = { key: string; aliases: Set<string> };

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

function branchCandidates(row: Row): string[] {
  const keys = [...BRANCH_KEYS, ...EXTRA_BRANCH_KEYS];
  const values = keys.flatMap((key) => aliasValues(first(row, [key], "").trim())).filter(Boolean);
  return Array.from(new Set(values));
}

export function fallbackBranch(row: Row): string {
  const candidates = branchCandidates(row);
  return candidates.find((candidate) => !isAdminLikeBranch(candidate)) || candidates[0] || "genel-kasa";
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

function aliasValues(value: string): string[] {
  const clean = value.trim();
  if (!clean) return [];
  const aliases = new Set([clean]);
  const normalized = normalizeBranch(clean);
  const cashierNumber = normalized.match(/^cashier[_\s-]*(\d+)$/);
  const kasaNumber = normalized.match(/^kasa[_\s-]*(\d+)$/);
  if (cashierNumber) aliases.add(cashierNumber[1]);
  if (kasaNumber) aliases.add(kasaNumber[1]);
  return Array.from(aliases);
}

function isOpaqueId(value: string): boolean {
  const clean = value.trim();
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(clean)) return true;
  if (/^[0-9a-f]{24,}$/i.test(clean)) return true;
  return clean.length > 32 && !/\s/.test(clean);
}

function isDisplayBranch(value: string): boolean {
  const clean = value.trim();
  if (!clean || isAdminLikeBranch(clean) || isOpaqueId(clean)) return false;
  if (/^cashier[_\s-]*\d+$/i.test(clean)) return false;
  return /^\d+$/.test(clean) || /[a-zA-ZığüşöçİĞÜŞÖÇ]/.test(clean);
}

function branchKeyFromCandidates(candidates: string[]): string {
  const visible = candidates.filter(isDisplayBranch);
  const named = visible.find((candidate) => /[a-zA-ZığüşöçİĞÜŞÖÇ]/.test(candidate) && !/^kasa[_\s-]*\d+$/i.test(candidate));
  if (named) return named.trim();
  const kasaNumber = visible
    .map((candidate) => normalizeBranch(candidate).match(/^kasa[_\s-]*(\d+)$/)?.[1] || "")
    .find(Boolean);
  if (kasaNumber) return kasaNumber;
  return visible.find((candidate) => /^\d+$/.test(candidate.trim()))?.trim() || "";
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

function addGroup(groupsByKey: Map<string, BranchGroup>, key: string, candidates: string[], id = "") {
  if (!key) return;
  const group = groupsByKey.get(key) || { key, aliases: new Set<string>() };
  group.aliases.add(key);
  for (const candidate of candidates) {
    if (candidate && !isAdminLikeBranch(candidate)) group.aliases.add(candidate);
  }
  if (id) group.aliases.add(id);
  groupsByKey.set(key, group);
}

function buildBranchGroups(users: Row[], dataRows: Row[]): { groups: BranchGroup[]; cashierIds: Set<string>; adminIds: Set<string> } {
  const adminIds = new Set(users.filter((row) => !isCashierUser(row)).map(userId).filter(Boolean));
  const cashierIds = new Set(users.filter(isCashierUser).map(userId).filter(Boolean));
  const groupsByKey = new Map<string, BranchGroup>();
  const userGroups = new Map<string, BranchGroup>();

  for (const user of users.filter(isCashierUser)) {
    const candidates = branchCandidates(user);
    addGroup(userGroups, branchKeyFromCandidates(candidates), candidates, userId(user));
  }

  for (const row of dataRows.filter(isActive)) {
    const id = actorId(row);
    if (id && adminIds.has(id)) continue;
    const candidates = branchCandidates(row);
    addGroup(groupsByKey, branchKeyFromCandidates(candidates), candidates, id);
  }

  const targetGroups = groupsByKey.size > 0 ? groupsByKey : userGroups;
  for (const [key, userGroup] of Array.from(userGroups.entries())) {
    const group = targetGroups.get(key);
    if (!group) continue;
    for (const alias of Array.from(userGroup.aliases)) group.aliases.add(alias);
  }

  return {
    groups: Array.from(targetGroups.values()).sort((a, b) => a.key.localeCompare(b.key, "tr", { numeric: true })),
    cashierIds,
    adminIds
  };
}

function matchingGroup(row: Row, groups: BranchGroup[]): BranchGroup | undefined {
  const normalized = new Set(branchCandidates(row).map(normalizeBranch));
  if (normalized.size === 0) return undefined;
  return groups.find((group) => Array.from(group.aliases).some((alias) => normalized.has(normalizeBranch(alias))));
}

function isUnscopedLegacyRow(row: Row): boolean {
  return branchCandidates(row).length === 0;
}

function selectedGroup(selectedBranch: string, groups: BranchGroup[]): BranchGroup | undefined {
  const selected = normalizeBranch(selectedBranch);
  if (!selected) return undefined;
  return groups.find((group) => normalizeBranch(group.key) === selected || Array.from(group.aliases).some((alias) => normalizeBranch(alias) === selected));
}

function isRealBranchRow(row: Row, scope: ReturnType<typeof buildBranchGroups>): boolean {
  const id = actorId(row);
  if (id && scope.adminIds.has(id)) return false;
  if (matchingGroup(row, scope.groups)) return true;
  if (isUnscopedLegacyRow(row) && scope.groups.length > 0) return true;
  return Boolean(id && scope.cashierIds.has(id));
}

function filterRealBranches(rows: Row[], scope: ReturnType<typeof buildBranchGroups>): Row[] {
  return rows.filter((row) => isActive(row) && isRealBranchRow(row, scope));
}

function filterBranch(rows: Row[], group?: BranchGroup): Row[] {
  if (!group) return rows;
  return rows.filter((row) => matchingGroup(row, [group]) || isUnscopedLegacyRow(row));
}

function displayBranchForRow(row: Row, groups: BranchGroup[], activeGroup?: BranchGroup): string {
  return matchingGroup(row, groups)?.key || activeGroup?.key || groups[0]?.key || fallbackBranch(row);
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
  const scope = buildBranchGroups(usersAllRaw, [...customersResult.rows, ...productsResult.rows, ...salesResult.rows]);
  const activeGroup = selectedGroup(selectedBranch, scope.groups);
  const effectiveBranch = activeGroup?.key || "";
  const usersAll = usersAllRaw.filter((row) => isRealBranchRow(row, scope));
  const customersAll = filterRealBranches(customersResult.rows, scope);
  const productsAll = filterRealBranches(productsResult.rows, scope);
  const salesAll = filterRealBranches(salesResult.rows, scope);

  const users = filterBranch(usersAll, activeGroup);
  const customers = filterBranch(customersAll, activeGroup);
  const products = filterBranch(productsAll, activeGroup);
  const sales = filterBranch(salesAll, activeGroup);
  const today = todayKey();
  const todaySales = sales.filter((sale) => dateKey(saleDateRaw(sale)) === today);
  const branches = scope.groups.map((group) => group.key);

  const byBranchMap = new Map<string, PanelData["byBranch"][number]>();
  for (const branch of branches) ensureBranch(byBranchMap, branch);
  for (const user of usersAll) {
    const group = matchingGroup(user, scope.groups);
    if (group) ensureBranch(byBranchMap, group.key).userCount += 1;
  }
  for (const customer of customersAll) {
    ensureBranch(byBranchMap, displayBranchForRow(customer, scope.groups, activeGroup)).customerCount += 1;
  }
  for (const product of productsAll) {
    ensureBranch(byBranchMap, displayBranchForRow(product, scope.groups, activeGroup)).productCount += 1;
  }
  for (const sale of salesAll.filter((item) => dateKey(saleDateRaw(item)) === today)) {
    const item = ensureBranch(byBranchMap, displayBranchForRow(sale, scope.groups, activeGroup));
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
      branch: displayBranchForRow(customer, scope.groups, activeGroup),
      balance: balance(customer)
    })).sort((a, b) => a.name.localeCompare(b.name, "tr")).slice(0, 200),
    stock: products.map((product) => ({
      id: first(product, ["id"], ""),
      name: first(product, ["name", "product_name", "title", "urun_adi"], "-"),
      category: first(product, ["category", "kategori"], ""),
      branch: displayBranchForRow(product, scope.groups, activeGroup),
      stock: stock(product),
      price: price(product)
    })).sort((a, b) => a.name.localeCompare(b.name, "tr")).slice(0, 200),
    byBranch: Array.from(byBranchMap.values())
      .filter((item) => !effectiveBranch || normalizeBranch(item.branch) === normalizeBranch(effectiveBranch))
      .sort((a, b) => a.branch.localeCompare(b.branch, "tr")),
    debug: {
      apiCustomers: customersResult.rows.length,
      apiProducts: productsResult.rows.length,
      apiSales: salesResult.rows.length,
      filteredCustomers: customers.length,
      filteredProducts: products.length,
      selectedBranch: effectiveBranch || "Tüm Kasalar",
      matchedAliases: activeGroup ? activeGroup.aliases.size : scope.groups.reduce((total, group) => total + group.aliases.size, 0)
    }
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
