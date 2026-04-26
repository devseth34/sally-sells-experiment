const ARMS = [
  { value: null, label: "Random (production)" },
  { value: "sally_warm", label: "Warm — Jessica / Flash" },
  { value: "sally_confident", label: "Confident — Alice / Flash" },
  { value: "sally_direct", label: "Direct — Thandi / Cartesia" },
  { value: "sally_emotive", label: "Emotive — Jessica / v3" },
] as const;

interface Props {
  selected: string | null;
  onChange: (v: string | null) => void;
}

export function ArmPicker({ selected, onChange }: Props) {
  return (
    <div className="flex flex-col items-center gap-1">
      <label className="text-xs text-zinc-500">Force arm (dev mode)</label>
      <select
        className="bg-zinc-800 text-white text-sm px-3 py-1.5 rounded-md border border-zinc-700 focus:outline-none focus:ring-1 focus:ring-zinc-500"
        value={selected ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        {ARMS.map((a) => (
          <option key={a.value ?? "random"} value={a.value ?? ""}>
            {a.label}
          </option>
        ))}
      </select>
    </div>
  );
}
