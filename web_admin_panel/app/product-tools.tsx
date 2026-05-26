"use client";

import { useMemo, useState, useTransition } from "react";
import type { BranchOption } from "../lib/supabase-readonly";

type Product = {
  id: string;
  name: string;
  category: string;
  branch: string;
  stableBranchKey: string;
  stock: number;
  price: number;
};

type EditState = {
  id: string;
  name: string;
  category: string;
  stock: string;
  price: string;
  branchKey: string;
};

function money(value: number) {
  return new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY" }).format(value || 0);
}

function branchLabel(branches: BranchOption[], key: string) {
  return branches.find((branch) => branch.key === key)?.label || key.replace(/^branch_id:/, "") || "-";
}

async function requestJson(url: string, init: RequestInit) {
  const response = await fetch(url, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.success === false) {
    throw new Error(String(data?.error || "İşlem tamamlanamadı."));
  }
  return data;
}

export default function ProductTools({ branch, products, branches }: { branch: string; products: Product[]; branches: BranchOption[] }) {
  const [isPending, startTransition] = useTransition();
  const [message, setMessage] = useState("");
  const [editing, setEditing] = useState<EditState | null>(null);
  const [newProduct, setNewProduct] = useState({ name: "", category: "", stock: "0", price: "0" });
  const visibleProducts = useMemo(() => products.slice(0, 200), [products]);
  const selectedBranch = branch || "";
  const canCreate = Boolean(selectedBranch);

  function resetNewProduct() {
    setNewProduct({ name: "", category: "", stock: "0", price: "0" });
  }

  function submitCreate() {
    startTransition(async () => {
      setMessage("");
      try {
        await requestJson("/api/products", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...newProduct, branchKey: selectedBranch })
        });
        setMessage("Ürün eklendi.");
        resetNewProduct();
        window.location.reload();
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Ürün eklenemedi.");
      }
    });
  }

  function submitEdit() {
    if (!editing) return;
    startTransition(async () => {
      setMessage("");
      try {
        await requestJson("/api/products", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(editing)
        });
        setMessage("Ürün güncellendi.");
        setEditing(null);
        window.location.reload();
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Ürün güncellenemedi.");
      }
    });
  }

  return (
    <article id="products" className="panel stock-tools">
      <div className="panel-heading compact">
        <div className="panel-title">
          <h2>Ürün ve Stok Yönetimi</h2>
          <p>Bu panelde ürün ekleme ve stok/fiyat düzenleme yapılabilir. Kasa silme ve destructive işlemler masaüstü uygulamadan yapılır.</p>
        </div>
        {!canCreate && <span className="panel-note">Ürün eklemek için önce gerçek bir kasa seçin.</span>}
      </div>

      <form
        className="management-form"
        onSubmit={(event) => {
          event.preventDefault();
          submitCreate();
        }}
      >
        <strong>Yeni Ürün</strong>
        <div className="form-row three">
          <label>
            Ürün adı
            <input value={newProduct.name} onChange={(event) => setNewProduct((item) => ({ ...item, name: event.target.value }))} required maxLength={120} />
          </label>
          <label>
            Kategori
            <input value={newProduct.category} onChange={(event) => setNewProduct((item) => ({ ...item, category: event.target.value }))} maxLength={80} />
          </label>
          <label>
            Kasa
            <select value={selectedBranch} disabled>
              <option value="">{selectedBranch ? branchLabel(branches, selectedBranch) : "Kasa seçin"}</option>
            </select>
          </label>
        </div>
        <div className="form-row">
          <label>
            Stok
            <input type="number" min="0" step="1" value={newProduct.stock} onChange={(event) => setNewProduct((item) => ({ ...item, stock: event.target.value }))} required />
          </label>
          <label>
            Fiyat
            <input type="number" min="0" step="0.01" value={newProduct.price} onChange={(event) => setNewProduct((item) => ({ ...item, price: event.target.value }))} required />
          </label>
        </div>
        <button className="button button-primary" type="submit" disabled={isPending || !canCreate}>Ürün Ekle</button>
      </form>

      <div className="table-frame product-management-table">
        <table>
          <thead><tr><th>Ürün</th><th>Kategori</th><th>Kasa</th><th className="numeric">Stok</th><th className="numeric">Fiyat</th><th>İşlem</th></tr></thead>
          <tbody>
            {visibleProducts.length === 0 && <tr><td className="empty" colSpan={6}>Kayıt yok</td></tr>}
            {visibleProducts.map((product) => {
              const isEditing = editing?.id === product.id;
              return (
                <tr key={`${product.stableBranchKey}-${product.id || product.name}`}>
                  <td data-label="Ürün" className="strong-cell">
                    {isEditing ? <input value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} /> : product.name}
                  </td>
                  <td data-label="Kategori">
                    {isEditing ? <input value={editing.category} onChange={(event) => setEditing({ ...editing, category: event.target.value })} /> : (product.category || "-")}
                  </td>
                  <td data-label="Kasa">{branchLabel(branches, product.stableBranchKey)}</td>
                  <td data-label="Stok" className="numeric">
                    {isEditing ? <input type="number" min="0" step="1" value={editing.stock} onChange={(event) => setEditing({ ...editing, stock: event.target.value })} /> : product.stock}
                  </td>
                  <td data-label="Fiyat" className="numeric">
                    {isEditing ? <input type="number" min="0" step="0.01" value={editing.price} onChange={(event) => setEditing({ ...editing, price: event.target.value })} /> : money(product.price)}
                  </td>
                  <td data-label="İşlem">
                    {isEditing ? (
                      <div className="button-row compact">
                        <button className="button button-primary" type="button" disabled={isPending} onClick={submitEdit}>Kaydet</button>
                        <button className="button button-secondary" type="button" disabled={isPending} onClick={() => setEditing(null)}>Vazgeç</button>
                      </div>
                    ) : (
                      <button className="button button-secondary" type="button" onClick={() => setEditing({
                        id: product.id,
                        name: product.name,
                        category: product.category || "",
                        stock: String(product.stock),
                        price: String(product.price),
                        branchKey: product.stableBranchKey
                      })}>
                        Düzenle
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <footer className="panel-footer">
        <span>Toplam {new Intl.NumberFormat("tr-TR").format(products.length)} ürün</span>
        {message && <strong className="form-message inline">{message}</strong>}
      </footer>
    </article>
  );
}
