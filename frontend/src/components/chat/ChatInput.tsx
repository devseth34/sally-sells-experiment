import { useState } from "react";
import { Input } from "../ui/Input";
import { Button } from "../ui/Button";
import { Send } from "lucide-react";

interface ChatInputProps {
  onSend: (content: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    if (!value.trim() || disabled) return;
    onSend(value.trim());
    setValue("");
  };

  return (
    <div className="flex gap-2">
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSubmit()}
        placeholder="Type your message..."
        disabled={disabled}
      />
      <Button onClick={handleSubmit} disabled={disabled || !value.trim()}>
        <Send className="w-4 h-4" />
      </Button>
    </div>
  );
}