import { branchOf, loadPanelData, Row } from "../lib/supabase-readonly";
import { isPageAuthenticated } from "../lib/auth";
import BranchFilter from "./branch-filter";
import LoginForm from "./login-form";
import LogoutButton from "./logout-button";
import ProductTools from "./product-tools";

export const dynamic = "force-dynamic";

function money(value: number) {
  return new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY" }).format(value || 0);
}

function numberText(value: number) {
  return new Intl.NumberFormat("tr-TR").format(value || 0);
}

function dateText(value: unknown) {
  const raw = value ? String(value) : "";
  if (!raw) return "-";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return new Intl.DateTimeFormat("tr-TR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function first(row: Row, keys: string[], fallback = "-") {
  for (const key of keys) {
    const value = row[key];
    if (value !== undefined && value !== null && String(value).trim() !== "") return String(value);
  }
  return fallback;
}

function balanceClass(value: number) {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "neutral";
}

function branchLabel(value: string) {
  const clean = String(value || "").trim() || "genel-kasa";
  if (clean === "genel-kasa") return "genel-kasa";
  if (/^\d+$/.test(clean)) return `Kasa ${clean}`;
  const spaced = clean
    .replace(/[_-]+/g, " ")
    .replace(/\bkasa\s*(\d+)\b/gi, "Kasa $1")
    .replace(/\bbranch\s*(\d+)\b/gi, "Kasa $1")
    .replace(/\bprofile\s*(\d+)\b/gi, "Profil $1");
  return spaced.charAt(0).toLocaleUpperCase("tr-TR") + spaced.slice(1);
}

function isAdminLikeBranch(value: string) {
  const clean = String(value || "").trim().toLocaleLowerCase("tr-TR");
  return !clean || clean.includes("admin") || clean.includes("genel") || clean.includes("manager") || clean.includes("yonetici") || clean.includes("yönetici");
}

function isRealBranch(value: string) {
  return !isAdminLikeBranch(value);
}

function firstNumber(row: Row, keys: string[]) {
  for (const key of keys) {
    const value = row[key];
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      const number = Number(String(value).replace(",", "."));
      return Number.isFinite(number) ? number : 0;
    }
  }
  return 0;
}

function saleDateRaw(row: Row) {
  return first(row, ["created_at", "sale_date", "date", "createdAt", "timestamp", "sold_at", "datetime", "tarih"], "");
}

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

function rowBranch(row: Row, selectedBranch = "") {
  return (
    branchOf(row)
      || first(row, ["cashier_id", "device_id", "user_id", "cashier", "kasa", "branch", "profile"], "")
      || selectedBranch
      || "genel-kasa"
  );
}

function Icon({ name }: { name: "overview" | "cash" | "users" | "box" | "moves" | "branches" | "report" | "settings" | "refresh" | "chevron" | "download" | "menu" }) {
  const paths = {
    overview: "M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3V10.5Z",
    cash: "M4 7h16v10H4V7Zm3 3h2m6 4h2m-5-5a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
    users: "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8-1a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM3 19a5 5 0 0 1 10 0H3Zm10.5 0a4 4 0 0 1 7.5 0h-7.5Z",
    box: "M4 8.5 12 4l8 4.5v7L12 20l-8-4.5v-7Zm8 3.5 8-4.5M12 12 4 7.5m8 4.5v8",
    moves: "M4 17h4l3-9 4 8 2-5h3",
    branches: "M5 8h14M7 8v11m10-11v11M4 19h16M8 5h8",
    report: "M7 4h7l3 3v13H7V4Zm7 0v4h4M9 12h6M9 16h6M9 8h3",
    settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm8 4h-2m-12 0H4m13.66-5.66-1.42 1.42M7.76 16.24l-1.42 1.42m11.32 0-1.42-1.42M7.76 7.76 6.34 6.34",
    refresh: "M20 6v5h-5M4 18v-5h5m9.5-4A7 7 0 0 0 6.2 7.7M5.5 15A7 7 0 0 0 17.8 16.3",
    chevron: "m9 18 6-6-6-6",
    download: "M12 3v11m0 0 4-4m-4 4-4-4M5 19h14",
    menu: "M4 7h16M4 12h16M4 17h16"
  };

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="icon">
      <path d={paths[name]} />
    </svg>
  );
}

function Sidebar() {
  return (
    <aside className="sidebar">
      <details className="mobile-menu">
        <summary><Icon name="menu" /> Menü</summary>
        <a className="side-link active" href="#customers"><Icon name="users" /> Müşteriler</a>
        <a className="side-link" href="#products"><Icon name="box" /> Ürünler</a>
      </details>
      <div className="brand">
        <div className="brand-logo">
          <img src="/matadors-logo.jpg" alt="Matadors logo" />
        </div>
        <div>
          <strong>MATADORS</strong>
          <span>Yönetici Paneli</span>
        </div>
      </div>

      <nav className="side-nav" aria-label="Panel menüsü">
        <a className="side-link active" href="#">
          <Icon name="overview" />
          Özet
        </a>
      </nav>

      <div className="system-card">
        <strong>Matadors App</strong>
        <span>V1.1</span>
        <div className="system-status"><span className="status-dot" /> Sistem Aktif</div>
      </div>
    </aside>
  );
}

function StatCard({ tone, icon, label, value, hint }: { tone: "blue" | "green" | "purple" | "orange"; icon: "users" | "cash" | "box" | "moves"; label: string; value: string; hint: string }) {
  return (
    <article className="stat-card">
      <div className={`stat-icon ${tone}`}><Icon name={icon} /></div>
      <div className="stat-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{hint}</small>
      </div>
    </article>
  );
}

function Pager({ total, pageSize }: { total: number; pageSize: number }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="pager" aria-label="Sayfalama">
      <button type="button" disabled><Icon name="chevron" /></button>
      <button type="button" className="active">1</button>
      {pages > 1 && <button type="button">2</button>}
      {pages > 2 && <button type="button">3</button>}
      {pages > 4 && <span>...</span>}
      {pages > 3 && <button type="button">{pages}</button>}
      <button type="button" disabled={pages <= 1}><Icon name="chevron" /></button>
    </div>
  );
}

export default async function Page({ searchParams }: { searchParams?: { branch?: string } }) {
  if (!isPageAuthenticated()) {
    return <LoginForm />;
  }

  const selectedBranch = searchParams?.branch || "";
  const data = await loadPanelData(selectedBranch);
  const pageBranches = data.branches.filter(isRealBranch);
  const pageActiveBranch = data.selectedBranch && pageBranches.includes(data.selectedBranch) ? data.selectedBranch : "";
  const filteredBalances = data.balances.filter((item) => isRealBranch(item.branch) && (!pageActiveBranch || item.branch === pageActiveBranch));
  const filteredStock = data.stock.filter((item) => isRealBranch(item.branch) && (!pageActiveBranch || item.branch === pageActiveBranch));
  const filteredSales = data.sales.filter((item) => {
    const branch = rowBranch(item, pageActiveBranch);
    return isRealBranch(branch) && (!pageActiveBranch || branch === pageActiveBranch || branchLabel(branch) === branchLabel(pageActiveBranch));
  });
  const pageTodaySales = filteredSales.filter((sale) => saleDateRaw(sale).slice(0, 10) === todayKey());
  const pageSummary = {
    ...data.summary,
    customerCount: filteredBalances.length,
    productCount: filteredStock.length,
    totalBalance: filteredBalances.reduce((total, customer) => total + customer.balance, 0),
    totalStock: filteredStock.reduce((total, product) => total + product.stock, 0),
    saleCount: filteredSales.length,
    todayTotal: pageTodaySales.reduce((total, sale) => total + firstNumber(sale, ["total", "total_amount", "grand_total", "amount", "net_total", "tutar", "toplam"]), 0)
  };
  const pageActiveBranchLabel = pageActiveBranch ? branchLabel(pageActiveBranch) : "Tüm Kasalar";
  const activeBranchLabel = pageActiveBranchLabel;
  const visibleBalances = filteredBalances.slice(0, 10);
  const visibleStock = filteredStock.slice(0, 10);
  const debug = {
    ...data.debug,
    filteredCustomers: filteredBalances.length,
    filteredProducts: filteredStock.length
  };

  return (
    <div className="admin-layout">
      <Sidebar />

      <main className="content-shell">
        <header className="overview-card">
          <div className="overview-title">
            <span className="version-pill">v2</span>
            <h1>Özet</h1>
            <span>Sistem durumu ve genel bakış</span>
            <small>{activeBranchLabel} için son güncelleme: {dateText(pageSummary.updatedAt)}</small>
          </div>
          <div className="topbar-actions">
            <BranchFilter branches={pageBranches} selected={pageActiveBranch} />
            <a className="button button-secondary" href={pageActiveBranch ? `/?branch=${encodeURIComponent(pageActiveBranch)}` : "/"}>
              <Icon name="refresh" />
              Yenile
            </a>
            <LogoutButton />
          </div>
        </header>

        <section className="debug-strip">
          API customers: {numberText(debug.apiCustomers)}, products: {numberText(debug.apiProducts)}, sales: {numberText(debug.apiSales)}, filtered customers: {numberText(debug.filteredCustomers)}, filtered products: {numberText(debug.filteredProducts)}
        </section>

        {data.errors.length > 0 && (
          <section className="error-box">
            Veri alınamadı. Supabase bağlantısını kontrol edin.
          </section>
        )}

        <section className="metrics" aria-label="Özet kartları">
          <StatCard tone="blue" icon="users" label="Toplam Müşteri" value={numberText(pageSummary.customerCount)} hint="Aktif müşteriler" />
          <StatCard tone="green" icon="cash" label="Toplam Bakiye" value={money(pageSummary.totalBalance)} hint="Tüm müşterilerin bakiyesi" />
          <StatCard tone="purple" icon="box" label="Toplam Ürün" value={numberText(pageSummary.productCount)} hint="Stoktaki ürün sayısı" />
          <StatCard tone="orange" icon="moves" label="Toplam Stok" value={numberText(pageSummary.totalStock)} hint="Tüm ürün stokları" />
        </section>

        <section className="panel-grid primary-panels">
          <article id="customers" className="panel data-panel">
            <div className="panel-action-strip">
              <a className="button button-primary" href={`/api/customers/pdf${pageActiveBranch ? `?branch=${encodeURIComponent(pageActiveBranch)}` : ""}`}>
                <Icon name="download" />
                PDF İndir
              </a>
            </div>
            <div className="panel-heading">
              <div className="panel-title">
                <span className="panel-icon blue"><Icon name="users" /></span>
                <h2>Müşteri Bakiyeleri</h2>
              </div>
              <a className="view-all" href="#customers">Tümünü Gör <Icon name="chevron" /></a>
            </div>
            <div className="table-frame">
              <table>
                <thead><tr><th>Müşteri</th><th>Kasa</th><th className="numeric">Bakiye</th></tr></thead>
                <tbody>
                  {visibleBalances.length === 0 && <tr><td className="empty" colSpan={3}>Kayıt yok</td></tr>}
                  {visibleBalances.map((customer) => (
                    <tr key={`${customer.branch}-${customer.name}`}>
                      <td data-label="Müşteri" className="strong-cell">{customer.name}</td>
                      <td data-label="Kasa">{branchLabel(customer.branch || "genel-kasa")}</td>
                      <td data-label="Bakiye" className={`numeric ${balanceClass(customer.balance)}`}>{money(customer.balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <footer className="panel-footer">
              <span>Toplam {numberText(filteredBalances.length)} müşteri</span>
              <Pager total={filteredBalances.length} pageSize={10} />
            </footer>
          </article>

          <article id="products" className="panel data-panel">
            <div className="panel-heading">
              <div className="panel-title">
                <span className="panel-icon purple"><Icon name="box" /></span>
                <h2>Ürün Stokları</h2>
              </div>
              <a className="view-all" href="#products">Tümünü Gör <Icon name="chevron" /></a>
            </div>
            <div className="table-frame">
              <table>
                <thead><tr><th>Ürün</th><th>Kasa</th><th className="numeric">Stok</th><th className="numeric">Fiyat</th></tr></thead>
                <tbody>
                  {visibleStock.length === 0 && <tr><td className="empty" colSpan={4}>Kayıt yok</td></tr>}
                  {visibleStock.map((product) => (
                    <tr key={`${product.branch}-${product.name}`}>
                      <td data-label="Ürün" className="strong-cell">{product.name}</td>
                      <td data-label="Kasa">{branchLabel(product.branch || "genel-kasa")}</td>
                      <td data-label="Stok" className="numeric">{numberText(product.stock)}</td>
                      <td data-label="Fiyat" className="numeric">{money(product.price)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <footer className="panel-footer">
              <span>Toplam {numberText(filteredStock.length)} ürün</span>
              <Pager total={filteredStock.length} pageSize={10} />
            </footer>
          </article>
        </section>

        <section className="panel-grid stock-action-section">
          <ProductTools branch={pageActiveBranch} products={filteredStock} />
        </section>

        <section id="branches" className="mini-grid">
          <article className="mini-card">
            <strong>Bugünkü satış</strong>
            <span>{money(pageSummary.todayTotal)}</span>
          </article>
          <article id="moves" className="mini-card">
            <strong>Satış adedi</strong>
            <span>{numberText(pageSummary.saleCount)}</span>
          </article>
          <article className="mini-card">
            <strong>Kasa özeti</strong>
            <span>{numberText(pageBranches.length)} kasa</span>
          </article>
        </section>

        <footer className="page-footer">© 2025 Matadors App. Tüm hakları saklıdır.</footer>
      </main>
    </div>
  );
}
