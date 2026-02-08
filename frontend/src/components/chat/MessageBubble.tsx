
import { getPhaseLabel, getPhaseColor } from "../../constants";
import { formatTimestamp } from "../../lib/utils";
import type { MessageResponse } from "../../lib/api";

interface MessageBubbleProps {
  message: MessageResponse;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const phaseColor = getPhaseColor(message.phase);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div className={`max-w-[75%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-1`}>
        <div
          className={`px-3 py-2 rounded-lg text-sm leading-relaxed ${
            isUser
              ? "bg-zinc-700 text-white rounded-br-sm"
              : "bg-zinc-900 text-zinc-200 border border-zinc-800 rounded-bl-sm"
          }`}
        >
          {message.content}
        </div>
        <div className="flex items-center gap-2 px-1">
          <span className="text-[10px] text-zinc-600">
            {formatTimestamp(message.timestamp)}
          </span>
          <span
            className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider"
            style={{
              background: `${phaseColor}15`,
              color: phaseColor,
            }}
          >
            {getPhaseLabel(message.phase)}
          </span>
        </div>
      </div>
    </div>
  );
}