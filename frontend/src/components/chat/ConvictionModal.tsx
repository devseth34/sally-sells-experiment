import { useState } from "react";
import type { BotArm } from "../../lib/api";

interface ConvictionModalProps {
  onStart: (score: number, bot: BotArm) => void;
}

const BOT_OPTIONS: { id: BotArm; name: string; description: string }[] = [
  {
    id: "sally_nepq",
    name: "Sally",
    description: "Consultative — asks questions to understand your needs",
  },
  {
    id: "hank_hypes",
    name: "Hank",
    description: "Enthusiastic — shows you the ROI and opportunity",
  },
  {
    id: "ivy_informs",
    name: "Ivy",
    description: "Informational — provides neutral facts and details",
  },
];

export function ConvictionModal({ onStart }: ConvictionModalProps) {
  const [score, setScore] = useState<number | null>(null);
  const [selectedBot, setSelectedBot] = useState<BotArm>("sally_nepq");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 w-full max-w-md mx-4 max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-semibold text-white mb-2">
          Before we begin...
        </h2>

        {/* Bot Selector */}
        <p className="text-sm text-zinc-400 mb-3">Choose who you'd like to speak with:</p>
        <div className="flex flex-col gap-2 mb-6">
          {BOT_OPTIONS.map((bot) => (
            <button
              key={bot.id}
              onClick={() => setSelectedBot(bot.id)}
              className={`text-left px-4 py-3 rounded-lg border transition-all ${
                selectedBot === bot.id
                  ? "border-white bg-zinc-800"
                  : "border-zinc-700 bg-zinc-900 hover:border-zinc-500"
              }`}
            >
              <span className="text-sm font-medium text-white">{bot.name}</span>
              <span className="block text-xs text-zinc-500 mt-0.5">{bot.description}</span>
            </button>
          ))}
        </div>

        {/* Conviction Score */}
        <p className="text-sm text-zinc-400 mb-3">
          On a scale of 1-10, how likely are you to purchase a $10,000 AI
          program today?
        </p>

        <div className="grid grid-cols-5 gap-2 mb-6">
          {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
            <button
              key={n}
              onClick={() => setScore(n)}
              className={`h-10 rounded-md text-sm font-medium transition-all ${
                score === n
                  ? "bg-white text-black scale-105"
                  : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-white"
              }`}
            >
              {n}
            </button>
          ))}
        </div>

        <div className="flex justify-between text-[10px] text-zinc-600 mb-6 px-1">
          <span>Not at all likely</span>
          <span>Extremely likely</span>
        </div>

        <button
          onClick={() => score && onStart(score, selectedBot)}
          disabled={!score}
          className="w-full h-10 rounded-md text-sm font-medium bg-white text-black hover:bg-zinc-200 disabled:opacity-30 disabled:pointer-events-none transition-colors"
        >
          Start Conversation
        </button>
      </div>
    </div>
  );
}
