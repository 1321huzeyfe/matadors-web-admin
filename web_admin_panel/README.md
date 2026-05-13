# MatadorsApp Yonetici Web Paneli

Bu klasor bagimsiz Next.js yonetici panelidir. Masaustu uygulamaya, SQLite dosyalarina ve Supabase sync/queue sistemine dokunmaz. Panel Supabase'den sadece okuma yapar.

## Yerel Test

```powershell
cd C:\Users\huzeyfe\Desktop\MatadorsApp_V1.1\web_admin_panel
copy .env.example .env.local
npm install
npm run dev
```

Panel varsayilan olarak acilir:

```text
http://localhost:3000
```

## Netlify Deploy

Netlify icin gerekli dosya:

```text
netlify.toml
```

Netlify ayarlari:

- Base directory: `web_admin_panel` (repo kokunden deploy ediyorsan mutlaka ayarla)
- Build command: `npm run build`
- Publish directory: `.next`
- Plugin: `@netlify/plugin-nextjs`
- Node version: `20`

Asil deploy kaynagi bu `web_admin_panel` klasorudur. Netlify'da base directory bos kalirsa repo kokundeki eski dosyalar veya yanlis klasor yayinlanabilir. `deploy_ready/` sadece manuel zip icin opsiyoneldir ve Netlify kaynak deploy'una dahil edilmemelidir.

Canli sitede eski dashboard gorunurse Netlify'da once `Clear cache and deploy site` ile yeniden deploy al. Eski static dosyalar (`public/index.html`, `public/app.js`, `public/styles.css`) kaldirildi; root sayfayi artik Next.js `app/page.tsx` uretir.

Netlify UI'da Environment Variables bolumune asagidaki degerleri ekleyin. Bu degerleri `NEXT_PUBLIC_` ile baslatmayin; server tarafinda kalmalilar.

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=replace-with-server-only-service-role-key
ADMIN_PANEL_PASSWORD=change-this-password
ADMIN_SESSION_SECRET=change-this-long-random-secret
```

`SUPABASE_SERVICE_ROLE_KEY`, `ADMIN_PANEL_PASSWORD` ve `ADMIN_SESSION_SECRET` sadece Next.js server component/API route tarafinda kullanilir ve tarayiciya gonderilmez.

## Deploy paketine girmesi gerekenler

Deploy/repo icinde sadece kaynak dosyalar bulunmali:

- `app/`
- `lib/`
- `public/matadors-logo.jpg`
- `package.json`
- `next.config.mjs`
- `tsconfig.json`
- `netlify.toml`
- `.env.example`
- `.gitignore`
- `.netlifyignore`
- `README.md`

Deploy/repo icine kesinlikle alinmayacaklar:

- `.env.local`
- `.env`
- `.env.*.local`
- `node_modules/`
- `.next/`
- `.netlify/`
- `out/`
- `dist/`

Canli ortamda secret degerleri dosyadan degil Netlify Environment Variables uzerinden verilir.

## Hazir deploy paketi

Bu klasorde `deploy_ready/` temiz production kaynak paketi olarak hazirlanir. Zip alip Netlify'a manuel yuklemek istersen sadece `deploy_ready` klasorunun icini zipleyin.

Paketi yeniden olusturmak icin:

```powershell
cd C:\Users\huzeyfe\Desktop\MatadorsApp_V1.1\web_admin_panel
.\prepare_deploy.ps1
```

`deploy_ready` icinde olmasi gerekenler:

- `app/`
- `lib/`
- `public/`
- `package.json`
- `package-lock.json`
- `next.config.mjs`
- `tsconfig.json`
- `next-env.d.ts`
- `netlify.toml`
- `README.md`
- `.env.example`

`deploy_ready` icine alinmayanlar:

- `.env.local`
- `.next/`
- `node_modules/`
- cache/log/temp dosyalari

Netlify manuel deploy sirasinda Environment Variables bolumunde `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ADMIN_PANEL_PASSWORD` ve `ADMIN_SESSION_SECRET` degerlerini tanimlayin.

Ilk acilista dashboard render edilmez. Once `ADMIN_PANEL_PASSWORD` ile giris yapilir. Giris basarili olunca imzali httpOnly cookie olusur. Cikis butonu bu cookie'yi temizler ve tekrar sifre ekranina doner.

## Okunan Tablolar

- `users`
- `customers`
- `products`
- `sales`

Kasa filtresi icin panel su alanlari sirayla kontrol eder:

- `branch_id`
- `profile_id`
- `kasa_id`
- `cashier_id`

## Not

Vercel'e ozel `vercel.json` ve eski root `api/` serverless dosyalari kaldirildi. Aktif API route artik Next.js app router icindedir:

```text
app/api/panel/route.ts
```
