"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { BranchDeleteSummary } from "../lib/supabase-readonly";

function numberText(value: number) {
  return new Intl.NumberFormat("tr-TR").format(value || 0);
}

export default function BranchManagement({ branches }: { branches: BranchDeleteSummary[] }) {
  const router = useRouter();
  const [target, setTarget] = useState<BranchDeleteSummary | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const canDelete = Boolean(target && confirmation === target.label && !busy);
  const total = useMemo(() => {
    if (!target) return 0;
    return target.customers + target.products + target.sales + target.users;
  }, [target]);

  function closeModal() {
    if (busy) return;
    setTarget(null);
    setConfirmation("");
  }

  async function deleteBranch() {
    if (!target || !canDelete) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/branches/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          branchKey: target.key,
          branchLabel: target.label,
          confirmation
        })
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) {
        setMessage(result.error || "Kasa silinemedi.");
        return;
      }
      setMessage(
        `Silindi: ${numberText(result.deleted?.sales || 0)} satış, ${numberText(result.deleted?.products || 0)} ürün, ${numberText(result.deleted?.customers || 0)} müşteri, ${numberText(result.deleted?.users || 0)} kullanıcı.`
      );
      setTarget(null);
      setConfirmation("");
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section id="branch-management" className="panel branch-management">
      <div className="panel-heading compact">
        <div className="panel-title">
          <h2>Kasa Yönetimi</h2>
        </div>
      </div>
      <div className="branch-management-list">
        {branches.length === 0 && <p className="branch-management-empty">Görünen aktif kasa yok.</p>}
        {branches.map((branch) => (
          <article className="branch-row" key={branch.key}>
            <div className="branch-row-main">
              <strong>{branch.label}</strong>
              <span>{branch.key}</span>
            </div>
            <div className="branch-row-counts" aria-label={`${branch.label} kayıt sayıları`}>
              <span>{numberText(branch.customers)} müşteri</span>
              <span>{numberText(branch.products)} ürün</span>
              <span>{numberText(branch.sales)} satış</span>
              <span>{numberText(branch.users)} kullanıcı</span>
            </div>
            <button
              type="button"
              className="button button-danger branch-delete-button"
              onClick={() => {
                setTarget(branch);
                setConfirmation("");
                setMessage("");
              }}
            >
              Kasa Sil
            </button>
          </article>
        ))}
      </div>
      {message && <p className="form-message">{message}</p>}

      {target && (
        <div className="modal-backdrop" role="presentation" onMouseDown={closeModal}>
          <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-branch-title" onMouseDown={(event) => event.stopPropagation()}>
            <h3 id="delete-branch-title">Kasa Sil</h3>
            <p className="danger-copy">
              Bu işlem geri alınamaz. Bu kasaya ait müşteri, ürün, satış ve kullanıcı kayıtları kalıcı olarak silinecek.
            </p>
            <div className="delete-summary">
              <strong>{target.label}</strong>
              <span>{target.key}</span>
              <dl>
                <div><dt>Müşteri</dt><dd>{numberText(target.customers)}</dd></div>
                <div><dt>Ürün</dt><dd>{numberText(target.products)}</dd></div>
                <div><dt>Satış</dt><dd>{numberText(target.sales)}</dd></div>
                <div><dt>Kullanıcı</dt><dd>{numberText(target.users)}</dd></div>
              </dl>
              <small>Toplam {numberText(total)} kayıt hedeflenecek. API silmeden önce sayımı tekrar doğrular.</small>
            </div>
            <label className="confirm-label">
              <span>Onay için kasa adını aynen yazın: <strong>{target.label}</strong></span>
              <input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoFocus />
            </label>
            <div className="confirm-actions">
              <button type="button" className="button button-ghost" onClick={closeModal} disabled={busy}>Vazgeç</button>
              <button type="button" className="button button-danger" onClick={deleteBranch} disabled={!canDelete}>
                {busy ? "Siliniyor..." : "Kalıcı Olarak Sil"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
