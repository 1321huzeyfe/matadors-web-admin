"use client";

type Product = {
  id: string;
  name: string;
  category: string;
  branch: string;
  stableBranchKey?: string;
  stock: number;
  price: number;
};

function money(value: number) {
  return new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY" }).format(value || 0);
}

export default function ProductTools({ branch, products }: { branch: string; products: Product[] }) {
  const visibleProducts = products.slice(0, 60);

  return (
    <article className="panel stock-tools">
      <div className="panel-heading compact">
        <div className="panel-title">
          <h2>Ürün Stokları</h2>
        </div>
        <span className="panel-note">Salt okunur; ürün ve stok yönetimi masaüstü uygulamadan yapılır.</span>
      </div>

      <div className="stock-tools-grid">
        {visibleProducts.length === 0 && <p className="form-message">Gösterilecek ürün yok.</p>}
        {visibleProducts.map((product) => (
          <div className="tool-card" key={`${branch || product.branch}-${product.id}`}>
            <strong>{product.name}</strong>
            <span>{product.category || "Kategori yok"}</span>
            <span>Stok: {product.stock}</span>
            <span>{money(product.price)}</span>
          </div>
        ))}
      </div>
    </article>
  );
}
