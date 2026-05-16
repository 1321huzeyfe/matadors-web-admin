export type Row = Record<string, unknown>;

export type PanelData = {
  errors: string[];
  branches: BranchOption[];
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
  branchManagement: BranchDeleteSummary[];
  balances: Array<{ name: string; branch: string; stableBranchKey: string; balance: number }>;
  stock: Array<{ id: string; name: string; category: string; branch: string; stableBranchKey: string; stock: number; price: number }>;
  unmatchedBalances: Array<{ name: string; balance: number }>;
  unmatchedStock: Array<{ id: string; name: string; category: string; stock: number; price: number }>;
  byBranch: Array<{ branch: string; stableBranchKey: string; todayTotal: number; saleCount: number; customerCount: number; productCount: number; userCount: number }>;
  debug: {
    buildVersion: string;
    dropdownBranches: string[];
    warning: string;
    warnings: string[];
    dataBranchKeys: string[];
    activeBranchKeys: string[];
    activeUserBranchKeys: string[];
    systemBranchKeys: string[];
    inactiveBranchKeys: string[];
    visibleBranchKeys: string[];
    userBranchesWithoutData: string[];
    dataBranchesWithoutUser: string[];
    sampleCustomerBranchKeys: string[];
    sampleProductBranchKeys: string[];
    sampleSaleBranchKeys: string[];
    rawUsersCount: number;
    activeUsersCount: number;
    cashierCandidates: CashierDebugRow[];
    rejectedCashiers: Array<CashierDebugRow & { reason: string }>;
    apiCustomers: number;
    apiProducts: number;
    apiSales: number;
    filteredCustomers: number;
    filteredProducts: number;
    selectedBranch: string;
    selectedKey: string;
    customersBefore: number;
    customersAfter: number;
    productsBefore: number;
    productsAfter: number;
    salesBefore: number;
    salesAfter: number;
    unmatchedCustomers: number;
    unmatchedProducts: number;
  };
};

const TABLES = ["users", "customers", "products", "sales"] as const;
const STABLE_BRANCH_KEYS = ["branch_id", "kasa_id", "profile_id", "owner_id", "cashier_id", "user_id"] as const;
const BUILD_VERSION = "branch-visibility-delete-v9";
const HUMAN_USER_LABEL_KEYS = ["display_name", "name", "full_name"] as const;
const SYSTEM_BRANCH_VALUES = ["kasa_ops", "kasa_perf", "ops", "perf", "performance", "benchmark", "loadtest", "test", "seed", "demo", "dev", "internal"] as const;
export type BranchOption = { key: string; label: string };
export type BranchDeleteSummary = { key: string; label: string; customers: number; products: number; sales: number; users: number };
type BranchGroup = { key: string; label: string; aliases: Set<string> };
type CashierDebugRow = {
  role: string;
  username: string;
  branch_id: string;
  display_name: string;
  name: string;
  full_name: string;
  archived: unknown;
  is_active: unknown;
};

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
  return first(row, STABLE_BRANCH_KEYS);
}

function cleanBranchValue(value: unknown): string {
  const clean = stringValue(value).trim();
  const lowered = clean.toLowerCase();
  if (!clean || lowered === "null" || lowered === "undefined") return "";
  return clean.replace(/\s+/g, " ");
}

function branchKeyValue(value: unknown): string {
  const clean = cleanBranchValue(value).toLowerCase().replace(/\s+/g, "");
  return clean.startsWith("branch_id:") ? clean.slice("branch_id:".length) : clean;
}

function canonicalBranchKey(value: unknown): string {
  const clean = branchKeyValue(value);
  return clean && !isAdminLikeBranch(clean) ? `branch_id:${clean}` : "";
}

function stableBranchKey(row: Row): string {
  for (const field of STABLE_BRANCH_KEYS) {
    const key = canonicalBranchKey(valueOf(row, field));
    if (key) return key;
  }
  return "";
}

function stableBranchAliases(row: Row): string[] {
  const aliases = STABLE_BRANCH_KEYS
    .map((field) => {
      return canonicalBranchKey(valueOf(row, field));
    })
    .filter(Boolean);
  return Array.from(new Set(aliases));
}

function userBranchValue(row: Row): string {
  return cleanBranchValue(valueOf(row, "branch_id"));
}

function userBranchKey(row: Row): string {
  return canonicalBranchKey(userBranchValue(row));
}

function userBranchAliases(row: Row): string[] {
  const aliases = new Set(stableBranchAliases(row));
  const value = userBranchValue(row);
  if (value && !isAdminLikeBranch(value)) {
    const key = canonicalBranchKey(value);
    if (key) aliases.add(key);
  }
  const id = userId(row);
  if (id) {
    const idKey = canonicalBranchKey(id);
    if (idKey) aliases.add(idKey);
  }
  return Array.from(aliases);
}

function hasRealBranchId(row: Row): boolean {
  return Boolean(stableBranchKey(row));
}

export function fallbackBranch(row: Row): string {
  return stableBranchKey(row) || "genel-kasa";
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
  const archivedText = String(archived ?? "").trim().toLowerCase();
  const activeText = String(is_active ?? "").trim().toLowerCase();
  const archivedFlag = archived === true || archived === 1 || archivedText === "1" || archivedText === "true" || archivedText === "yes";
  const inactiveFlag = is_active === false || is_active === 0 || activeText === "0" || activeText === "false" || activeText === "no";
  return !archivedFlag && !inactiveFlag;
}

function isAdminLikeBranch(branch: string): boolean {
  const clean = normalizeBranch(branch);
  if (clean.includes("admin") || clean.includes("genel") || clean.includes("manager")) return true;
  return !clean || clean === "admin" || clean === "manager" || clean === "genel-kasa" || clean === "general" || clean === "yonetici" || clean === "yönetici";
}

export function isSystemBranchValue(value: string): boolean {
  const clean = normalizeBranch(value).replace(/[^a-z0-9ığüşöç]+/gi, "_").replace(/^_+|_+$/g, "");
  if (!clean) return false;
  const tokens = clean.split("_").filter(Boolean);
  return SYSTEM_BRANCH_VALUES.some((blocked) => clean === blocked || tokens.includes(blocked));
}

function isDropdownBranchValue(value: string): boolean {
  const clean = value.trim();
  return Boolean(clean) && !isSystemBranchValue(clean) && !isAdminLikeBranch(clean);
}

function roleValue(row: Row): string {
  return first(row, ["role", "user_type", "type"], "").toLowerCase();
}

function isCashierLikeRole(row: Row): boolean {
  const role = roleValue(row);
  return role === "cashier" || role === "kasa" || role.includes("cashier");
}

function hasBlockedCashierValue(row: Row): boolean {
  return ["username", "branch_id", "kasa_id", "profile_id", "owner_id", "cashier_id", "user_id", ...HUMAN_USER_LABEL_KEYS]
    .some((key) => isSystemBranchValue(first(row, [key], "")));
}

function blockedCashierField(row: Row): string {
  return ["username", "branch_id", "kasa_id", "profile_id", "owner_id", "cashier_id", "user_id", ...HUMAN_USER_LABEL_KEYS]
    .find((key) => isSystemBranchValue(first(row, [key], ""))) || "";
}

function isCashierCandidate(row: Row): boolean {
  const branchId = first(row, ["branch_id"], "").trim();
  return isCashierLikeRole(row) || Boolean(branchId && !isAdminLikeBranch(branchId));
}

function cashierRejectReason(row: Row): string {
  const branchId = first(row, ["branch_id"], "").trim();
  if (!isActive(row)) return "inactive";
  if (!isCashierCandidate(row)) return "wrong_role";
  if (!branchId) return "no_branch_id";
  const blockedField = blockedCashierField(row);
  if (blockedField) return `blocked_${blockedField}`;
  if (!isDropdownBranchValue(branchId)) return "blocked_branch_id";
  return "";
}

function cashierDebugRow(row: Row): CashierDebugRow {
  return {
    role: first(row, ["role", "user_type", "type"], ""),
    username: first(row, ["username"], ""),
    branch_id: first(row, ["branch_id"], ""),
    display_name: first(row, ["display_name"], ""),
    name: first(row, ["name"], ""),
    full_name: first(row, ["full_name"], ""),
    archived: valueOf(row, "archived") ?? null,
    is_active: valueOf(row, "is_active") ?? null
  };
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
  const branchId = first(row, ["branch_id"], "").trim();
  return isActive(row) && isCashierCandidate(row) && isDropdownBranchValue(branchId) && !hasBlockedCashierValue(row);
}

function actorId(row: Row): string {
  return first(row, ["cashier_id", "user_id"], "");
}

function userId(row: Row): string {
  return first(row, ["id", "cashier_id", "user_id"], "");
}

export function branchValueFromKey(key: string): string {
  return key.split(":").slice(1).join(":");
}

export function labelFromValue(value: string): string {
  const clean = value.trim();
  if (!clean) return "Kasa";
  const compact = clean.toLowerCase().replace(/[^a-z0-9ığüşöç]/gi, "");
  if (/^kasa\d+$/i.test(compact)) return `Kasa ${compact.replace(/^kasa/i, "")}`;
  if (/^\d+$/.test(clean)) return `Kasa ${clean}`;
  const spaced = clean.replace(/[_-]+/g, " ");
  return spaced.charAt(0).toLocaleUpperCase("tr-TR") + spaced.slice(1);
}

function labelForRow(row: Row, key: string): string {
  return first(row, HUMAN_USER_LABEL_KEYS, "") || labelFromValue(branchValueFromKey(key));
}

function uniqueBranchOptions(groups: BranchGroup[]): BranchOption[] {
  const labelCounts = new Map<string, number>();
  for (const group of groups) labelCounts.set(group.label, (labelCounts.get(group.label) || 0) + 1);
  return groups.map((group) => ({
    key: group.key,
    label: labelCounts.get(group.label)! > 1 ? `${group.label} (${branchValueFromKey(group.key).slice(-4)})` : group.label
  }));
}

function addGroup(groupsByKey: Map<string, BranchGroup>, key: string, label: string, aliases: string[]) {
  if (!key) return;
  const group = groupsByKey.get(key) || { key, label, aliases: new Set<string>() };
  if (!group.label || group.label === labelFromValue(branchValueFromKey(group.key))) group.label = label;
  group.aliases.add(key);
  for (const alias of aliases) group.aliases.add(alias);
  groupsByKey.set(key, group);
}

function withStableBranch(row: Row): Row {
  return { ...row, stableBranchKey: stableBranchKey(row) };
}

function buildBranchGroups(users: Row[]): { groups: BranchGroup[]; cashierIds: Set<string>; adminIds: Set<string> } {
  const cashierUsers = users.filter(isCashierUser);
  const adminIds = new Set(users.filter((row) => !isCashierUser(row)).map(userId).filter(Boolean));
  const cashierIds = new Set(cashierUsers.map(userId).filter(Boolean));
  const groupsByKey = new Map<string, BranchGroup>();

  for (const user of cashierUsers) {
    const key = userBranchKey(user);
    addGroup(groupsByKey, key, labelForRow(user, key), userBranchAliases(user));
  }

  return {
    groups: Array.from(groupsByKey.values()).sort((a, b) => a.label.localeCompare(b.label, "tr", { numeric: true })),
    cashierIds,
    adminIds
  };
}

function branchGroupsFromKeys(keys: string[], labelsByKey: Map<string, string>): BranchGroup[] {
  const groupsByKey = new Map<string, BranchGroup>();
  for (const key of keys) {
    addGroup(groupsByKey, key, labelsByKey.get(key) || labelFromValue(branchValueFromKey(key)), [key]);
  }
  return Array.from(groupsByKey.values()).sort((a, b) => a.label.localeCompare(b.label, "tr", { numeric: true }));
}

function countRowsForGroup(rows: Row[], group: BranchGroup): number {
  return rows.filter((row) => matchingGroup(row, [group])).length;
}

function matchingGroup(row: Row, groups: BranchGroup[]): BranchGroup | undefined {
  const normalized = new Set(stableBranchAliases(row).map(normalizeBranch));
  if (normalized.size === 0) return undefined;
  return groups.find((group) => Array.from(group.aliases).some((alias) => normalized.has(normalizeBranch(alias))));
}

function selectedGroup(selectedBranch: string, groups: BranchGroup[]): BranchGroup | undefined {
  const selected = normalizeBranch(selectedBranch);
  if (!selected) return undefined;
  return groups.find((group) => normalizeBranch(group.key) === selected);
}

function isRealBranchRow(row: Row, scope: ReturnType<typeof buildBranchGroups>): boolean {
  if (matchingGroup(row, scope.groups)) return true;
  return false;
}

function filterRealBranches(rows: Row[], scope: ReturnType<typeof buildBranchGroups>): Row[] {
  return rows.filter((row) => isActive(row) && isRealBranchRow(row, scope));
}

function filterUnmatchedRows(rows: Row[], scope: ReturnType<typeof buildBranchGroups>): Row[] {
  return rows.filter((row) => isActive(row) && !isRealBranchRow(row, scope));
}

function filterBranch(rows: Row[], group?: BranchGroup): Row[] {
  if (!group) return rows;
  return rows.filter((row) => matchingGroup(row, [group]));
}

function displayBranchForRow(row: Row, groups: BranchGroup[], activeGroup?: BranchGroup): string {
  return matchingGroup(row, groups)?.label || activeGroup?.label || labelFromValue(branchOf(row));
}

function ensureBranch(map: Map<string, PanelData["byBranch"][number]>, group: BranchGroup) {
  const key = group.key;
  if (!map.has(key)) {
    map.set(key, { branch: group.label, stableBranchKey: key, todayTotal: 0, saleCount: 0, customerCount: 0, productCount: 0, userCount: 0 });
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
  const cashierCandidateRows = usersResult.rows.filter(isCashierCandidate);
  const rejectedCashiers = cashierCandidateRows
    .map((row) => ({ ...cashierDebugRow(row), reason: cashierRejectReason(row) }))
    .filter((row) => row.reason)
    .slice(0, 10);
  const usersAllRaw = usersResult.rows.filter(isActive).map(withStableBranch);
  const customersRaw = customersResult.rows.filter(hasRealBranchId).map(withStableBranch);
  const productsRaw = productsResult.rows.filter(hasRealBranchId).map(withStableBranch);
  const salesRaw = salesResult.rows.filter(hasRealBranchId).map(withStableBranch);
  const activeCustomersRaw = customersRaw.filter(isActive);
  const activeProductsRaw = productsRaw.filter(isActive);
  const activeSalesRaw = salesRaw.filter(isActive);
  const labelsByKey = new Map<string, string>();
  const dataBranchKeySet = new Set<string>();

  for (const row of [...activeCustomersRaw, ...activeProductsRaw, ...activeSalesRaw]) {
    const key = stableBranchKey(row);
    if (!key) continue;
    dataBranchKeySet.add(key);
    if (!labelsByKey.has(key)) labelsByKey.set(key, labelFromValue(branchValueFromKey(key)));
  }

  const dataBranchKeys = Array.from(dataBranchKeySet).sort();
  const systemBranchKeys = Array.from(new Set(cashierCandidateRows
    .filter(hasBlockedCashierValue)
    .map((row) => userBranchKey(row) || stableBranchKey(row))
    .filter(Boolean))).sort();
  const inactiveBranchKeys = Array.from(new Set(cashierCandidateRows
    .filter((row) => !isActive(row))
    .map((row) => userBranchKey(row) || stableBranchKey(row))
    .filter(Boolean))).sort();
  const activeUserBranchKeys = Array.from(new Set(cashierCandidateRows
    .filter((row) => isActive(row) && !hasBlockedCashierValue(row) && isDropdownBranchValue(userBranchValue(row)))
    .map(userBranchKey)
    .filter(Boolean))).sort();

  for (const user of cashierCandidateRows) {
    const key = userBranchKey(user);
    if (key && !labelsByKey.has(key)) labelsByKey.set(key, labelForRow(user, key));
  }

  const systemBranchSet = new Set(systemBranchKeys);
  const inactiveBranchSet = new Set(inactiveBranchKeys);
  const visibleBranchKeys = Array.from(new Set([...dataBranchKeys, ...activeUserBranchKeys]))
    .filter((key) => key && !systemBranchSet.has(key) && !inactiveBranchSet.has(key) && isDropdownBranchValue(branchValueFromKey(key)))
    .sort();
  const userBranchKeys = Array.from(new Set([...activeUserBranchKeys, ...systemBranchKeys, ...inactiveBranchKeys])).sort();
  const userBranchKeySet = new Set(userBranchKeys);
  const dataBranchKeyLookup = new Set(dataBranchKeys);
  const userBranchesWithoutData = userBranchKeys.filter((key) => !dataBranchKeyLookup.has(key));
  const dataBranchesWithoutUser = dataBranchKeys.filter((key) => !userBranchKeySet.has(key));
  const warnings: string[] = [];
  if (visibleBranchKeys.length === 0) warnings.push("visibleBranchKeys empty; check branch classification.");

  const visibleGroups = branchGroupsFromKeys(visibleBranchKeys, labelsByKey);
  const scope = { groups: visibleGroups, cashierIds: new Set<string>(), adminIds: new Set<string>() };
  const activeGroup = selectedGroup(selectedBranch, visibleGroups);
  const requestedSelectedKey = selectedBranch ? normalizeBranch(selectedBranch) : "";
  const selectedIsBlocked = Boolean(requestedSelectedKey && (systemBranchSet.has(requestedSelectedKey) || inactiveBranchSet.has(requestedSelectedKey)));
  if (selectedIsBlocked) warnings.push("Selected branch is inactive or system-owned; data hidden.");
  const effectiveBranch = activeGroup?.key || (selectedIsBlocked ? selectedBranch : "");
  const visibleBranchSet = new Set(visibleBranchKeys.map(normalizeBranch));
  const rowInVisibleBranch = (row: Row) => visibleBranchSet.has(normalizeBranch(stableBranchKey(row)));
  const rowInSelectedBranch = (row: Row) => activeGroup ? matchingGroup(row, [activeGroup]) : false;

  const usersAll = usersAllRaw.filter((row) => visibleBranchSet.has(normalizeBranch(stableBranchKey(row))));
  const customersAll = selectedIsBlocked ? [] : (visibleBranchKeys.length > 0 ? activeCustomersRaw.filter(rowInVisibleBranch) : activeCustomersRaw);
  const productsAll = selectedIsBlocked ? [] : (visibleBranchKeys.length > 0 ? activeProductsRaw.filter(rowInVisibleBranch) : activeProductsRaw);
  const salesAll = selectedIsBlocked ? [] : (visibleBranchKeys.length > 0 ? activeSalesRaw.filter(rowInVisibleBranch) : activeSalesRaw);
  const unmatchedCustomers = visibleBranchKeys.length > 0 ? activeCustomersRaw.filter((row) => !rowInVisibleBranch(row)) : [];
  const unmatchedProducts = visibleBranchKeys.length > 0 ? activeProductsRaw.filter((row) => !rowInVisibleBranch(row)) : [];

  const users = activeGroup ? usersAll.filter(rowInSelectedBranch) : usersAll;
  const customers = activeGroup ? customersAll.filter(rowInSelectedBranch) : customersAll;
  const products = activeGroup ? productsAll.filter(rowInSelectedBranch) : productsAll;
  const sales = activeGroup ? salesAll.filter(rowInSelectedBranch) : salesAll;
  const today = todayKey();
  const todaySales = sales.filter((sale) => dateKey(saleDateRaw(sale)) === today);
  const branches = uniqueBranchOptions(visibleGroups);
  const branchManagement = visibleGroups.map((group) => ({
    key: group.key,
    label: branches.find((branch) => branch.key === group.key)?.label || group.label,
    customers: countRowsForGroup(customersRaw, group),
    products: countRowsForGroup(productsRaw, group),
    sales: countRowsForGroup(salesRaw, group),
    users: usersResult.rows.filter((row) => userBranchAliases(row).some((alias) => normalizeBranch(alias) === normalizeBranch(group.key))).length
  }));

  const byBranchMap = new Map<string, PanelData["byBranch"][number]>();
  for (const group of visibleGroups) ensureBranch(byBranchMap, group);
  for (const customer of customersAll) {
    const group = matchingGroup(customer, visibleGroups);
    if (group) ensureBranch(byBranchMap, group).customerCount += 1;
  }
  for (const product of productsAll) {
    const group = matchingGroup(product, visibleGroups);
    if (group) ensureBranch(byBranchMap, group).productCount += 1;
  }
  for (const sale of salesAll.filter((item) => dateKey(saleDateRaw(item)) === today)) {
    const group = matchingGroup(sale, visibleGroups);
    if (group) {
      const item = ensureBranch(byBranchMap, group);
      item.saleCount += 1;
      item.todayTotal += saleTotal(sale);
    }
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
    branchManagement,
    balances: customers.map((customer) => ({
      name: first(customer, ["name", "full_name", "customer_name", "ad_soyad"], "-"),
      branch: displayBranchForRow(customer, visibleGroups, activeGroup),
      stableBranchKey: stableBranchKey(customer),
      balance: balance(customer)
    })).sort((a, b) => a.name.localeCompare(b.name, "tr")).slice(0, 200),
    stock: products.map((product) => ({
      id: first(product, ["id"], ""),
      name: first(product, ["name", "product_name", "title", "urun_adi"], "-"),
      category: first(product, ["category", "kategori"], ""),
      branch: displayBranchForRow(product, visibleGroups, activeGroup),
      stableBranchKey: stableBranchKey(product),
      stock: stock(product),
      price: price(product)
    })).sort((a, b) => a.name.localeCompare(b.name, "tr")).slice(0, 200),
    unmatchedBalances: unmatchedCustomers.map((customer) => ({
      name: first(customer, ["name", "full_name", "customer_name", "ad_soyad"], "-"),
      balance: balance(customer)
    })).sort((a, b) => a.name.localeCompare(b.name, "tr")).slice(0, 200),
    unmatchedStock: unmatchedProducts.map((product) => ({
      id: first(product, ["id"], ""),
      name: first(product, ["name", "product_name", "title", "urun_adi"], "-"),
      category: first(product, ["category", "kategori"], ""),
      stock: stock(product),
      price: price(product)
    })).sort((a, b) => a.name.localeCompare(b.name, "tr")).slice(0, 200),
    byBranch: Array.from(byBranchMap.values())
      .filter((item) => !effectiveBranch || item.stableBranchKey === effectiveBranch)
      .sort((a, b) => a.branch.localeCompare(b.branch, "tr")),
    debug: {
      buildVersion: BUILD_VERSION,
      dataBranchKeys,
      activeUserBranchKeys,
      inactiveBranchKeys,
      systemBranchKeys,
      visibleBranchKeys,
      dropdownBranches: branches.map((branch) => branch.label),
      warning: warnings[0] || "",
      warnings,
      activeBranchKeys: visibleBranchKeys,
      userBranchesWithoutData,
      dataBranchesWithoutUser,
      sampleCustomerBranchKeys: customersRaw.map(stableBranchKey).filter(Boolean).slice(0, 10),
      sampleProductBranchKeys: productsRaw.map(stableBranchKey).filter(Boolean).slice(0, 10),
      sampleSaleBranchKeys: salesRaw.map(stableBranchKey).filter(Boolean).slice(0, 10),
      rawUsersCount: usersResult.rows.length,
      activeUsersCount: usersAllRaw.length,
      cashierCandidates: cashierCandidateRows.map(cashierDebugRow).slice(0, 10),
      rejectedCashiers,
      apiCustomers: customersResult.rows.length,
      apiProducts: productsResult.rows.length,
      apiSales: salesResult.rows.length,
      filteredCustomers: customers.length,
      filteredProducts: products.length,
      selectedBranch: activeGroup?.label || "Tüm Kasalar",
      selectedKey: effectiveBranch || "ALL",
      customersBefore: customersRaw.filter(isActive).length,
      customersAfter: customers.length,
      productsBefore: productsRaw.filter(isActive).length,
      productsAfter: products.length,
      salesBefore: salesRaw.filter(isActive).length,
      salesAfter: sales.length,
      unmatchedCustomers: unmatchedCustomers.length,
      unmatchedProducts: unmatchedProducts.length
    }
  };
}

export async function loadWritableBranches(): Promise<Array<{ branch: string; branchValue: string; cashierId: string; label: string }>> {
  const users = (await select("users")).filter(isCashierUser);
  const rows = users
    .map((user) => {
      const branch = userBranchKey(user);
      return {
        branch,
        branchValue: branchValueFromKey(branch),
        cashierId: first(user, ["id", "cashier_id"], ""),
        label: labelForRow(user, branch)
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
