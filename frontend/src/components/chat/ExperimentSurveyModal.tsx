import { useState } from "react";

interface ExperimentSurveyModalProps {
  onStart: (score: number, name: string, email: string) => void;
}

export function ExperimentSurveyModal({ onStart }: ExperimentSurveyModalProps) {
  const [score, setScore] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");

  const canStart = score !== null && name.trim() !== "" && email.trim() !== "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 w-full max-w-md mx-4">
        <h2 className="text-lg font-semibold text-white mb-2">
          Quick question before we start
        </h2>

        <div className="space-y-3 mb-6">
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Your full name"
              className="w-full h-10 rounded-md bg-zinc-800 border border-zinc-700 px-3 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500 transition-colors"
            />
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full h-10 rounded-md bg-zinc-800 border border-zinc-700 px-3 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500 transition-colors"
            />
          </div>
        </div>

        <p className="text-sm text-zinc-400 mb-6">
          On a scale of 1-10, how interested are you in using AI to improve your
          mortgage business?
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
          <span>Not at all interested</span>
          <span>Extremely interested</span>
        </div>

        <button
          onClick={() => canStart && onStart(score!, name.trim(), email.trim())}
          disabled={!canStart}
          className="w-full h-10 rounded-md text-sm font-medium bg-white text-black hover:bg-zinc-200 disabled:opacity-30 disabled:pointer-events-none transition-colors"
        >
          Start Chat
        </button>
      </div>
    </div>
  );
}
