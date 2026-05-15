"use client";

import { useRouter } from "next/navigation";

type BranchOption = { key: string; label: string };

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
          <option key={branch.key} value={branch.key}>{branch.label}</option>
        ))}
      </select>
    </label>
  );
}
