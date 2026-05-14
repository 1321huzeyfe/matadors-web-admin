"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

type Product = {
  id: string;
  name: string;
  category: string;
  branch: string;
  stock: number;
  price: number;
};

function money(value: number) {
  return new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY" }).format(value || 0);
}

export default function ProductTools({ branch, products }: { branch: string; products: Product[] }) {
  const router = useRouter();
  const [selectedId, setSelectedId] = useState(products[0]?.id || "");
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [price, setPrice] = useState("");
  const [stock, setStock] = useState("");
  const [delta, setDelta] = useState("1");
  const [message, setMessage] = useState("");
  const selected = useMemo(() => products.find((item) => item.id === selectedId), [products, selectedId]);
  const disabled = !branch;

  async function submit(payload: Record<string, unknown>) {
    setMessage("");
    const response = await fetch("/api/products", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branch, ...payload })
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) {
      setMessage(result.error || "İşlem yapılamadı.");
      return;
    }
    setMessage("Kaydedildi.");
    router.refresh();
  }

  return (
    <article className="panel stock-tools">
      <div className="panel-heading compact">
        <div className="panel-title">
          <h2>Stok Takip ve Giriş</h2>
        </div>
        {disabled && <span className="panel-note">Ürün işlemi için gerçek bir kasa seçin.</span>}
      </div>

      <div className="stock-tools-grid">
        <form
          className="tool-card"
          onSubmit={(event) => {
            event.preventDefault();
            submit({ action: "create", name, category, price: Number(price), stock: Number(stock) });
          }}
        >
          <strong>Yeni Ürün</strong>
          <input disabled={disabled} value={name} onChange={(event) => setName(event.target.value)} placeholder="Ürün adı" />
          <input disabled={disabled} value={category} onChange={(event) => setCategory(event.target.value)} placeholder="Kategori" />
          <div className="form-row">
            <input disabled={disabled} value={price} onChange={(event) => setPrice(event.target.value)} placeholder="Fiyat" inputMode="decimal" />
            <input disabled={disabled} value={stock} onChange={(event) => setStock(event.target.value)} placeholder="Stok" inputMode="decimal" />
          </div>
          <button className="button button-primary" disabled={disabled} type="submit">Ürün Ekle</button>
        </form>

        <form
          className="tool-card"
          onSubmit={(event) => {
            event.preventDefault();
            if (!selected) return;
            submit({
              action: "update",
              productId: selected.id,
              name: name || selected.name,
              category: category || selected.category,
              price: price === "" ? selected.price : Number(price)
            });
          }}
        >
          <strong>Seçili Ürün</strong>
          <select disabled={disabled || products.length === 0} value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
            {products.map((product) => (
              <option key={product.id} value={product.id}>{product.name} | {money(product.price)} | Stok {product.stock}</option>
            ))}
          </select>
          <div className="form-row">
            <input disabled={disabled} value={price} onChange={(event) => setPrice(event.target.value)} placeholder="Yeni fiyat" inputMode="decimal" />
            <input disabled={disabled} value={delta} onChange={(event) => setDelta(event.target.value)} placeholder="Stok değişimi" inputMode="decimal" />
          </div>
          <div className="button-row">
            <button className="button button-secondary" disabled={disabled || !selected} type="button" onClick={() => submit({ action: "adjust", productId: selectedId, delta: Math.abs(Number(delta || 0)) })}>Stok Artır</button>
            <button className="button button-secondary" disabled={disabled || !selected} type="button" onClick={() => submit({ action: "adjust", productId: selectedId, delta: -Math.abs(Number(delta || 0)) })}>Stok Azalt</button>
          </div>
          <div className="button-row">
            <button className="button button-primary" disabled={disabled || !selected} type="submit">Fiyatı Düzenle</button>
            <button className="button button-danger" disabled={disabled || !selected} type="button" onClick={() => submit({ action: "deactivate", productId: selectedId })}>Pasifleştir</button>
          </div>
        </form>
      </div>
      {message && <p className="form-message">{message}</p>}
    </article>
  );
}
