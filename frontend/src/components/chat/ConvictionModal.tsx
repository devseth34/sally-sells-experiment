import { useState } from "react";

interface ConvictionModalProps {
  onStart: (score: number) => void;
}

export function ConvictionModal({ onStart }: ConvictionModalProps) {
  const [score, setScore] = useState<number | null>(null);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 w-full max-w-md mx-4">
        <h2 className="text-lg font-semibold text-white mb-2">
          Before we begin...
        </h2>
        <p className="text-sm text-zinc-400 mb-6">
          On a scale of 1-10, how likely are you to purchase a $10,000 AI
          Discovery Workshop today?
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
          onClick={() => score && onStart(score)}
          disabled={!score}
          className="w-full h-10 rounded-md text-sm font-medium bg-white text-black hover:bg-zinc-200 disabled:opacity-30 disabled:pointer-events-none transition-colors"
        >
          Start Conversation
        </button>
      </div>
    </div>
  );
}