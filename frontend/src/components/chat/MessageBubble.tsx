import { cn } from "../../lib/utils";
import { Badge } from "../ui/Badge";
import type { Message } from "../../types";
import { format } from "date-fns";

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[70%] rounded-lg px-4 py-2.5",
          isUser
            ? "bg-white text-zinc-900"
            : "bg-zinc-800 text-zinc-100 border border-zinc-700"
        )}
      >
        <p className="text-sm leading-relaxed">{message.content}</p>
        <div className={cn(
          "flex items-center gap-2 mt-2 pt-2 border-t",
          isUser ? "border-zinc-200" : "border-zinc-700"
        )}>
          <Badge phase={message.phase} size="sm" />
          <span className={cn(
            "text-[10px]",
            isUser ? "text-zinc-500" : "text-zinc-500"
          )}>
            {format(message.timestamp, "HH:mm")}
          </span>
        </div>
      </div>
    </div>
  );
}