"use client";

import { useRouter } from "next/navigation";

type BranchOption = { key: string; label: string };

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

export default function BranchFilter({ branches, selected }: { branches: BranchOption[]; selected: string }) {
  const router = useRouter();

  function changeBranch(value: string) {
    router.push(value ? `/?branch=${encodeURIComponent(value)}` : "/");
    router.refresh();
  }

  return (
    <label className="select-field">
      <span>Kasa Secin</span>
      <select name="branch" value={selected} aria-label="Kasa secin" onChange={(event) => changeBranch(event.target.value)}>
        <option value="">Tum Kasalar</option>
        {branches.map((branch) => (
          <option key={branch.key} value={branch.key}>{branch.label || branchLabel(branch.key)}</option>
        ))}
      </select>
    </label>
  );
}
