import { getPhaseLabel, getPhaseColor } from "../../constants";
import { formatTimestamp } from "../../lib/utils";
import type { MessageResponse } from "../../lib/api";

interface MessageBubbleProps {
  message: MessageResponse;
}

/**
 * Renders message text with clickable links.
 * Stripe checkout URLs become a styled payment button.
 * TidyCal URLs become a styled booking button.
 * Other URLs render as regular clickable links.
 */
function renderWithLinks(text: string) {
  // Split on any URL, keeping the URL as a separate part
  const urlRegex = /(https?:\/\/[^\s]+)/g;
  const parts = text.split(urlRegex);

  return parts.map((part, i) => {
    // Stripe checkout link → green payment button
    if (part.startsWith("https://checkout.stripe.com")) {
      return (
        <a
          key={i}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 my-2 px-5 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-500 no-underline font-semibold text-sm transition-colors"
        >
          💳 Secure Your Spot — $10,000
        </a>
      );
    }

    // TidyCal booking link → blue booking button
    if (part.startsWith("https://tidycal.com")) {
      return (
        <a
          key={i}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 my-2 px-5 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-500 no-underline font-semibold text-sm transition-colors"
        >
          📅 Book Free Workshop
        </a>
      );
    }

    // Any other URL → regular clickable link
    if (/^https?:\/\//.test(part)) {
      return (
        <a
          key={i}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-400 underline hover:text-blue-300 break-all"
        >
          {part}
        </a>
      );
    }

    return <span key={i}>{part}</span>;
  });
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const phaseColor = getPhaseColor(message.phase);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div className={`max-w-[75%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-1`}>
        <div
          className={`px-3 py-2 rounded-lg text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? "bg-zinc-700 text-white rounded-br-sm"
              : "bg-zinc-900 text-zinc-200 border border-zinc-800 rounded-bl-sm"
          }`}
        >
          {renderWithLinks(message.content)}
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