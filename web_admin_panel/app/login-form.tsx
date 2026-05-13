"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginForm() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password })
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(payload.error || "Şifre hatalı.");
        return;
      }
      setPassword("");
      router.refresh();
    } catch (_error) {
      setError("Giriş yapılamadı.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-card">
        <p className="eyebrow">MatadorsApp</p>
        <h1>Yönetici Girişi</h1>
        <form onSubmit={submit} className="login-form">
          <label>
            <span>Panel şifresi</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              autoFocus
              required
            />
          </label>
          {error && <p className="form-error">{error}</p>}
          <button className="button" type="submit" disabled={loading}>
            {loading ? "Kontrol ediliyor" : "Giriş Yap"}
          </button>
        </form>
      </section>
    </main>
  );
}
