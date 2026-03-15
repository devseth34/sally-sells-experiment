import { useState } from "react";
import type { BotArm } from "../../lib/api";

interface BotSwitcherProps {
  currentArm: string;
  onSwitch: (newBot: BotArm) => void;
  disabled?: boolean;
}

const BOTS: { id: BotArm; name: string }[] = [
  { id: "sally_nepq", name: "Sally" },
  { id: "hank_hypes", name: "Hank" },
  { id: "ivy_informs", name: "Ivy" },
];

export function BotSwitcher({ currentArm, onSwitch, disabled }: BotSwitcherProps) {
  const [open, setOpen] = useState(false);

  const available = BOTS.filter((b) => b.id !== currentArm);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        disabled={disabled}
        className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors disabled:opacity-30"
      >
        Switch bot ▾
      </button>

      {open && (
        <div className="absolute top-6 right-0 bg-zinc-800 border border-zinc-700 rounded-lg shadow-lg z-50 py-1 min-w-[120px]">
          {available.map((bot) => (
            <button
              key={bot.id}
              onClick={() => {
                onSwitch(bot.id);
                setOpen(false);
              }}
              className="w-full text-left px-3 py-2 text-xs text-zinc-300 hover:bg-zinc-700 transition-colors"
            >
              Switch to {bot.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
