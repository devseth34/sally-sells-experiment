import { useState, useRef, useEffect } from "react";
import { Header } from "../components/layout/Header";
import { PhaseIndicator } from "../components/chat/PhaseIndicator";
import { MessageBubble } from "../components/chat/MessageBubble";
import { ChatInput } from "../components/chat/ChatInput";
import { Card } from "../components/ui/Card";
import { formatTime, generateId } from "../lib/utils";
import { PHASE_ORDER } from "../constants";
import type { Message, NEPQPhase } from "../types";
import { Clock, AlertCircle } from "lucide-react";

export function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentPhase, setCurrentPhase] = useState<NEPQPhase>("CONNECTION");
  const [elapsed, setElapsed] = useState(0);
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Timer
  useEffect(() => {
    const timer = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = (content: string) => {
    const userMsg: Message = {
      id: generateId(),
      role: "user",
      content,
      timestamp: new Date(),
      phase: currentPhase,
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsTyping(true);

    // Simulate AI response
    setTimeout(() => {
      const currentIndex = PHASE_ORDER.indexOf(currentPhase);
      const nextPhase = currentIndex < PHASE_ORDER.length - 1 
        ? PHASE_ORDER[currentIndex + 1] 
        : "TERMINATED" as NEPQPhase;
      
      setCurrentPhase(nextPhase);
      
      const aiMsg: Message = {
        id: generateId(),
        role: "assistant",
        content: `[Simulated ${nextPhase} response] Based on what you've shared about "${content.slice(0, 50)}..."`,
        timestamp: new Date(),
        phase: nextPhase,
      };
      setMessages((prev) => [...prev, aiMsg]);
      setIsTyping(false);
    }, 1500);
  };

  const isNearTimeLimit = elapsed > 540; // 9 minutes

  return (
    <div className="h-screen flex flex-col bg-zinc-950">
      <Header />
      
      {/* Phase Bar */}
      <div className="px-6 py-3 border-b border-zinc-800 bg-zinc-900/50 flex items-center justify-between">
        <PhaseIndicator currentPhase={currentPhase} />
        <div className="flex items-center gap-4">
          {isNearTimeLimit && (
            <div className="flex items-center gap-1.5 text-amber-400 text-xs">
              <AlertCircle className="w-3.5 h-3.5" />
              <span>Approaching time limit</span>
            </div>
          )}
          <div className="flex items-center gap-1.5 text-zinc-400 text-xs font-mono">
            <Clock className="w-3.5 h-3.5" />
            {formatTime(elapsed)}
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl mx-auto space-y-4">
          {messages.length === 0 && (
            <Card className="p-8 text-center">
              <p className="text-zinc-400 text-sm">
                Start the conversation. Sally will guide prospects through the NEPQ methodology.
              </p>
            </Card>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          {isTyping && (
            <div className="flex justify-start">
              <div className="bg-zinc-800 rounded-lg px-4 py-3 border border-zinc-700">
                <div className="flex gap-1">
                  <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce" />
                  <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce [animation-delay:0.1s]" />
                  <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce [animation-delay:0.2s]" />
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="p-4 border-t border-zinc-800 bg-zinc-900">
        <div className="max-w-3xl mx-auto">
          <ChatInput onSend={handleSend} disabled={currentPhase === "TERMINATED"} />
        </div>
      </div>
    </div>
  );
}