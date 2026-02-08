import { useState, useEffect, useRef } from "react";
import { Header } from "../components/layout/Header.tsx";
import { PhaseIndicator } from "../components/chat/PhaseIndicator.tsx";
import { MessageBubble } from "../components/chat/MessageBubble.tsx";
import { ChatInput } from "../components/chat/ChatInput.tsx";
import { ConvictionModal } from "../components/chat/ConvictionModal.tsx";
import { createSession, sendMessage } from "../lib/api";
import { formatTime } from "../lib/utils";
import type { MessageResponse } from "../lib/api";

export function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentPhase, setCurrentPhase] = useState("CONNECTION");
  const [messages, setMessages] = useState<MessageResponse[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionEnded, setSessionEnded] = useState(false);
  const [preConviction, setPreConviction] = useState<number | null>(null);

  const [seconds, setSeconds] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (sessionId && !sessionEnded) {
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [sessionId, sessionEnded]);

  const handleStartSession = async (score: number) => {
    try {
      setIsLoading(true);
      const res = await createSession(score);
      setSessionId(res.session_id);
      setCurrentPhase(res.current_phase);
      setPreConviction(res.pre_conviction);
      setMessages([res.greeting]);
      setShowModal(false);
      setSeconds(0);
    } catch (err) {
      console.error("Failed to create session:", err);
      alert("Failed to connect to backend. Is the server running on port 8000?");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendMessage = async (content: string) => {
    if (!sessionId || isLoading) return;
    try {
      setIsLoading(true);
      const res = await sendMessage(sessionId, content);
      setMessages((prev) => [...prev, res.user_message, res.assistant_message]);
      setCurrentPhase(res.current_phase);
      if (res.session_ended) {
        setSessionEnded(true);
      }
    } catch (err) {
      console.error("Failed to send message:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleNewSession = () => {
    setSessionId(null);
    setMessages([]);
    setCurrentPhase("CONNECTION");
    setSessionEnded(false);
    setPreConviction(null);
    setSeconds(0);
    if (timerRef.current) clearInterval(timerRef.current);
    setShowModal(true);
  };

  return (
    <div className="h-screen flex flex-col bg-zinc-950 text-white">
      <Header />

      {showModal && <ConvictionModal onStart={handleStartSession} />}

      {!sessionId && !showModal && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <h2 className="text-lg font-semibold mb-2">Sally Sells</h2>
            <p className="text-sm text-zinc-500 mb-6">
              NEPQ-powered sales agent for 100x Discovery Workshop
            </p>
            <button
              onClick={() => setShowModal(true)}
              className="h-10 px-6 rounded-md text-sm font-medium bg-white text-black hover:bg-zinc-200 transition-colors"
            >
              Start Conversation
            </button>
          </div>
        </div>
      )}

      {sessionId && (
        <>
          <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-800 bg-zinc-950/80 overflow-x-auto">
            <PhaseIndicator currentPhase={currentPhase} />
            <div className="flex items-center gap-3 shrink-0 ml-4">
              {preConviction && (
                <span className="text-[10px] text-zinc-500">
                  Pre-score: {preConviction}/10
                </span>
              )}
              <span
                className={`text-xs font-mono ${
                  seconds > 540
                    ? "text-red-400"
                    : seconds > 480
                    ? "text-amber-400"
                    : "text-zinc-500"
                }`}
              >
                {formatTime(seconds)}
              </span>
              {seconds > 540 && (
                <span className="text-[10px] text-red-400">Time limit</span>
              )}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-4">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            {isLoading && (
              <div className="flex justify-start mb-3">
                <div className="bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-500">
                  Sally is typing...
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <ChatInput
            onSend={handleSendMessage}
            disabled={isLoading || sessionEnded}
          />

          {sessionEnded && (
            <div className="px-4 py-3 bg-zinc-900 border-t border-zinc-800 flex items-center justify-between">
              <span className="text-xs text-zinc-400">
                Session completed — {currentPhase}
              </span>
              <button
                onClick={handleNewSession}
                className="h-8 px-3 rounded-md text-xs font-medium bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
              >
                New Session
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}