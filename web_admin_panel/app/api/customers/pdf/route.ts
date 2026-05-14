import { NextRequest, NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { PDFDocument, rgb } from "pdf-lib";
import fontkit from "@pdf-lib/fontkit";
import { isValidSessionToken, SESSION_COOKIE } from "../../../../lib/auth";
import { loadPanelData } from "../../../../lib/supabase-readonly";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function money(value: number) {
  return new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY" }).format(value || 0);
}

function dateText(date = new Date()) {
  return new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function branchLabel(value: string) {
  const clean = String(value || "").trim();
  if (/^\d+$/.test(clean)) return `Kasa ${clean}`;
  const spaced = clean
    .replace(/[_-]+/g, " ")
    .replace(/\bkasa\s*(\d+)\b/gi, "Kasa $1")
    .replace(/\bbranch\s*(\d+)\b/gi, "Kasa $1")
    .replace(/\bprofile\s*(\d+)\b/gi, "Profil $1");
  return spaced.charAt(0).toLocaleUpperCase("tr-TR") + spaced.slice(1);
}

export async function GET(request: NextRequest) {
  if (!isValidSessionToken(request.cookies.get(SESSION_COOKIE)?.value)) {
    return NextResponse.json({ ok: false, error: "Yetkisiz erisim." }, { status: 401 });
  }

  const selectedBranch = request.nextUrl.searchParams.get("branch") || "";
  const data = await loadPanelData(selectedBranch);
  const reportDate = dateText();
  const pdf = await PDFDocument.create();
  pdf.registerFontkit(fontkit);
  const fontBytes = await readFile(path.join(process.cwd(), "public", "fonts", "segoeui.ttf"));
  const font = await pdf.embedFont(fontBytes, { subset: true });
  const pageSize: [number, number] = [595.28, 841.89];
  const margin = 42;
  let page = pdf.addPage(pageSize);
  let y = pageSize[1] - margin;

  function newPage() {
    page = pdf.addPage(pageSize);
    y = pageSize[1] - margin;
  }

  function row(customerName: string, branch: string, amount: string, date: string, header = false) {
    if (y < 62) newPage();
    page.drawRectangle({
      x: margin,
      y: y - 7,
      width: pageSize[0] - margin * 2,
      height: 25,
      color: header ? rgb(0.93, 0.96, 1) : rgb(1, 1, 1)
    });
    const color = header ? rgb(0.04, 0.14, 0.32) : rgb(0.08, 0.11, 0.18);
    const size = header ? 10 : 9;
    page.drawText(customerName, { x: margin + 8, y, size, font, color });
    page.drawText(branch, { x: margin + 220, y, size, font, color });
    page.drawText(amount, { x: margin + 350, y, size, font, color });
    page.drawText(date, { x: margin + 440, y, size, font, color });
    y -= 25;
  }

  row("M\u00fc\u015fteri ad\u0131", "Kasa ad\u0131", "Bakiye durumu", "Tarih", true);
  if (data.balances.length === 0) {
    row("Kay\u0131t yok", "-", "-", reportDate);
  } else {
    for (const customer of data.balances) {
      row(customer.name, branchLabel(customer.branch), money(customer.balance), reportDate);
    }
  }

  const bytes = await pdf.save();
  return new NextResponse(Buffer.from(bytes), {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `attachment; filename="matadors-musteri-bakiye-${data.selectedBranch || "tum-kasalar"}.pdf"`,
      "Cache-Control": "no-store"
    }
  });
}
