import { getPhaseLabel, getPhaseColor } from "../../constants";
import { formatTimestamp } from "../../lib/utils";
import type { MessageResponse } from "../../lib/api";

interface MessageBubbleProps {
  message: MessageResponse;
  onInvitationClick?: (url: string) => void;
  hasRated?: boolean;
  hidePhase?: boolean;
}

/**
 * Renders message text with clickable links.
 * Invitation URLs (100x.inc/academy) become a gated button that triggers rating flow.
 * Stripe checkout URLs become a styled payment button (preserved for future use).
 * TidyCal URLs become a styled booking button (preserved for future use).
 * Other URLs render as regular clickable links.
 */
function renderWithLinks(
  text: string,
  onInvitationClick?: (url: string) => void,
  hasRated?: boolean,
) {
  // Split on any URL, keeping the URL as a separate part
  const urlRegex = /(https?:\/\/[^\s]+)/g;
  const parts = text.split(urlRegex);

  return parts.map((part, i) => {
    // Invitation link (100x.inc/academy) → gated purple button OR direct link if already rated
    if (part.includes("100x.inc/academy")) {
      if (hasRated) {
        return (
          <a
            key={i}
            href={part}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 my-2 px-5 py-2.5 bg-purple-600 text-white rounded-lg hover:bg-purple-500 no-underline font-semibold text-sm transition-colors"
          >
            Request Your Invitation
          </a>
        );
      }
      return (
        <button
          key={i}
          onClick={() => onInvitationClick?.(part)}
          className="inline-flex items-center gap-2 my-2 px-5 py-2.5 bg-purple-600 text-white rounded-lg hover:bg-purple-500 font-semibold text-sm transition-colors cursor-pointer border-none"
        >
          Request Your Invitation
        </button>
      );
    }

    // Stripe checkout link → green payment button (preserved for future use)
    if (part.startsWith("https://checkout.stripe.com")) {
      return (
        <a
          key={i}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 my-2 px-5 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-500 no-underline font-semibold text-sm transition-colors"
        >
          Secure Your Spot
        </a>
      );
    }

    // TidyCal booking link → blue booking button (preserved for future use)
    if (part.startsWith("https://tidycal.com")) {
      return (
        <a
          key={i}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 my-2 px-5 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-500 no-underline font-semibold text-sm transition-colors"
        >
          Book Free Workshop
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

export function MessageBubble({ message, onInvitationClick, hasRated, hidePhase }: MessageBubbleProps) {
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
          {renderWithLinks(message.content, onInvitationClick, hasRated)}
        </div>
        <div className="flex items-center gap-2 px-1">
          <span className="text-[10px] text-zinc-600">
            {formatTimestamp(message.timestamp)}
          </span>
          {!hidePhase && (
            <span
              className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider"
              style={{
                background: `${phaseColor}15`,
                color: phaseColor,
              }}
            >
              {getPhaseLabel(message.phase)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}