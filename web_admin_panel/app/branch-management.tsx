import type { BranchDeleteSummary } from "../lib/supabase-readonly";

function numberText(value: number) {
  return new Intl.NumberFormat("tr-TR").format(value || 0);
}

export default function BranchManagement({ branches }: { branches: BranchDeleteSummary[] }) {
  return (
    <section id="branch-management" className="panel branch-management">
      <div className="panel-heading compact">
        <div className="panel-title">
          <h2>Kasa Durumu</h2>
          <p>Kasa silme ve pasifleştirme işlemleri web panelden yapılmaz; yönetim masaüstü uygulamadan yapılır.</p>
        </div>
      </div>
      <div className="branch-management-list">
        {branches.length === 0 && <p className="branch-management-empty">Görünen kasa yok.</p>}
        {branches.map((branch) => (
          <article className={`branch-row ${branch.isActive ? "" : "branch-row-passive"}`} key={branch.key}>
            <div className="branch-row-main">
              <strong>{branch.label}</strong>
              <span>{branch.key}</span>
              <em>{branch.isActive ? "Aktif" : "Pasif"}</em>
            </div>
            <div className="branch-row-counts" aria-label={`${branch.label} kayıt sayıları`}>
              <span>{numberText(branch.customers)} müşteri</span>
              <span>{numberText(branch.products)} ürün</span>
              <span>{numberText(branch.sales)} satış</span>
              <span>{numberText(branch.users)} kullanıcı</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
