import { useState } from "react";
import { submitPostConviction } from "../../lib/api";
import type { PostConvictionResponse } from "../../lib/api";

interface PostConvictionModalProps {
  sessionId: string;
  preConviction: number | null;
  onComplete: (result: PostConvictionResponse) => void;
}

export function PostConvictionModal({ sessionId, preConviction, onComplete }: PostConvictionModalProps) {
  const [score, setScore] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<PostConvictionResponse | null>(null);

  const handleSubmit = async () => {
    if (!score) return;
    setSubmitting(true);
    try {
      const res = await submitPostConviction(sessionId, score);
      setResult(res);
    } catch (err) {
      console.error("Failed to submit post-conviction:", err);
    } finally {
      setSubmitting(false);
    }
  };

  if (result) {
    const cdsColor =
      result.cds_score > 0 ? "text-emerald-400" :
      result.cds_score < 0 ? "text-red-400" :
      "text-zinc-400";

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 w-full max-w-md mx-4">
          <h2 className="text-lg font-semibold text-white mb-4">
            Conviction Delta Score
          </h2>

          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="text-center">
              <p className="text-xs text-zinc-500 mb-1">Pre-Chat</p>
              <p className="text-2xl font-semibold text-zinc-400">{result.pre_conviction ?? "—"}</p>
            </div>
            <div className="text-center">
              <p className="text-xs text-zinc-500 mb-1">Post-Chat</p>
              <p className="text-2xl font-semibold text-white">{result.post_conviction}</p>
            </div>
            <div className="text-center">
              <p className="text-xs text-zinc-500 mb-1">CDS</p>
              <p className={`text-2xl font-semibold ${cdsColor}`}>
                {result.cds_score > 0 ? "+" : ""}{result.cds_score}
              </p>
            </div>
          </div>

          <div className="mb-4">
            <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${result.cds_score > 0 ? "bg-emerald-500" : result.cds_score < 0 ? "bg-red-500" : "bg-zinc-600"}`}
                style={{ width: `${Math.min(100, Math.max(10, (result.post_conviction / 10) * 100))}%` }}
              />
            </div>
          </div>

          <button
            onClick={() => onComplete(result)}
            className="w-full h-10 rounded-md text-sm font-medium bg-white text-black hover:bg-zinc-200 transition-colors"
          >
            Continue
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 w-full max-w-md mx-4">
        <h2 className="text-lg font-semibold text-white mb-2">
          One last question...
        </h2>
        <p className="text-sm text-zinc-400 mb-6">
          After this conversation, how likely are you now to purchase a $10,000 AI
          Discovery Workshop?
        </p>

        {preConviction && (
          <p className="text-xs text-zinc-600 mb-4">
            You rated {preConviction}/10 before the conversation.
          </p>
        )}

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
          onClick={handleSubmit}
          disabled={!score || submitting}
          className="w-full h-10 rounded-md text-sm font-medium bg-white text-black hover:bg-zinc-200 disabled:opacity-30 disabled:pointer-events-none transition-colors"
        >
          {submitting ? "Submitting..." : "Submit Score"}
        </button>
      </div>
    </div>
  );
}
