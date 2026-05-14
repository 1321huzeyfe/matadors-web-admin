const money = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY" });
const number = new Intl.NumberFormat("tr-TR");

const $ = (id) => document.getElementById(id);
const branchFilter = $("branchFilter");

function setText(id, value) {
  $(id).textContent = value;
}

function branchOf(row) {
  return row.branch_id || row.profile_id || row.kasa_id || row.cashier_id || "-";
}

async function getPanel() {
  const branch = encodeURIComponent(branchFilter.value || "");
  const response = await fetch(`/api/panel?branch=${branch}`, { cache: "no-store" });
  if (response.status === 401) {
    window.location.href = "/login";
    return null;
  }
  return response.json();
}

function rows(target, data, columns, emptyText) {
  const body = $(target);
  body.innerHTML = "";
  if (!data || data.length === 0) {
    body.innerHTML = `<tr><td colspan="${columns.length}" class="empty">${emptyText}</td></tr>`;
    return;
  }
  for (const item of data) {
    const tr = document.createElement("tr");
    tr.innerHTML = columns.map((fn) => `<td>${fn(item)}</td>`).join("");
    body.appendChild(tr);
  }
}

function syncBranches(branches) {
  const current = branchFilter.value;
  const options = ['<option value="">Tüm kasalar</option>'].concat(
    (branches || []).map((branch) => `<option value="${branch}">${branch}</option>`)
  );
  branchFilter.innerHTML = options.join("");
  branchFilter.value = current;
}

async function refresh() {
  const data = await getPanel();
  if (!data) return;
  syncBranches(data.branches);
  const errors = $("errorBox");
  if (data.errors && data.errors.length) {
    errors.hidden = false;
    errors.textContent = data.errors.join(" | ");
  } else {
    errors.hidden = true;
    errors.textContent = "";
  }
  setText("todayTotal", money.format(Number(data.summary.today_total || 0)));
  setText("saleCount", number.format(Number(data.summary.sale_count || 0)));
  setText("customerCount", number.format(Number(data.summary.customer_count || 0)));
  setText("productCount", number.format(Number(data.summary.product_count || 0)));
  setText("updatedAt", data.summary.updated_at || "-");
  rows("branchRows", data.by_branch, [
    (x) => x.branch || "-",
    (x) => x.role || "-",
    (x) => money.format(Number(x.today_total || 0)),
    (x) => number.format(Number(x.sale_count || 0)),
    (x) => number.format(Number(x.customer_count || 0)),
    (x) => number.format(Number(x.product_count || 0)),
  ], "Kasa özeti yok.");
  rows("salesRows", data.sales, [
    (x) => String(x.created_at || "-").replace("T", " ").slice(0, 19),
    branchOf,
    (x) => x.customer_name || x.customer_id || "-",
    (x) => money.format(Number(x.total || 0)),
  ], "Bugün satış yok.");
  rows("balanceRows", data.balances, [
    (x) => x.name || "-",
    (x) => x.branch || "-",
    (x) => money.format(Number(x.balance || 0)),
  ], "Müşteri yok.");
  rows("stockRows", data.stock, [
    (x) => x.name || "-",
    (x) => x.branch || "-",
    (x) => number.format(Number(x.stock || 0)),
    (x) => money.format(Number(x.price || 0)),
  ], "Ürün yok.");
}

$("refreshBtn").addEventListener("click", refresh);
branchFilter.addEventListener("change", refresh);
refresh();
setInterval(refresh, 60000);
