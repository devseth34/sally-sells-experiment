import { useState, useEffect, useRef } from "react";
import { MessageBubble } from "../components/chat/MessageBubble.tsx";
import { ChatInput } from "../components/chat/ChatInput.tsx";
import { ExperimentSurveyModal } from "../components/chat/ExperimentSurveyModal.tsx";
import { PostConvictionModal } from "../components/chat/PostConvictionModal.tsx";
import { createSession, sendMessage, endSession, endSessionBeacon, switchBot, clearVisitorMemory } from "../lib/api";
import { BotSwitcher } from "../components/chat/BotSwitcher.tsx";
import { formatTime } from "../lib/utils";
import type { MessageResponse, PostConvictionResponse, BotArm } from "../lib/api";

export function ExperimentPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageResponse[]>([]);
  const [showSurvey, setShowSurvey] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionEnded, setSessionEnded] = useState(false);
  const [preConviction, setPreConviction] = useState<number | null>(null);
  const [showPostModal, setShowPostModal] = useState(false);
  const [cdsResult, setCdsResult] = useState<PostConvictionResponse | null>(null);
  const [currentPhase, setCurrentPhase] = useState("CONVERSATION");

  // Bot switching state
  const [botDisplayName, setBotDisplayName] = useState<string>("AI Assistant");
  const [assignedArm, setAssignedArm] = useState<string>("sally_nepq");

  const [seconds, setSeconds] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const sessionIdRef = useRef<string | null>(null);
  const sessionEndedRef = useRef(false);

  // Keep refs in sync
  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);
  useEffect(() => { sessionEndedRef.current = sessionEnded; }, [sessionEnded]);

  // End session on tab close
  useEffect(() => {
    const handleUnload = () => {
      if (sessionIdRef.current && !sessionEndedRef.current) {
        endSessionBeacon(sessionIdRef.current);
      }
    };
    window.addEventListener("pagehide", handleUnload);
    window.addEventListener("beforeunload", handleUnload);
    return () => {
      window.removeEventListener("pagehide", handleUnload);
      window.removeEventListener("beforeunload", handleUnload);
    };
  }, []);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Timer
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
      // No bot selected — backend randomly assigns. experiment_mode = true.
      const res = await createSession(score, undefined, true);
      setSessionId(res.session_id);
      setCurrentPhase(res.current_phase);
      setPreConviction(res.pre_conviction);
      setBotDisplayName(res.bot_display_name);
      setAssignedArm(res.assigned_arm);
      setMessages([res.greeting]);
      setShowSurvey(false);
      setSeconds(0);
    } catch (err) {
      console.error("Failed to create session:", err);
      alert("Something went wrong. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendMessage = async (content: string) => {
    if (!sessionId || isLoading) return;

    const optimisticMsg: MessageResponse = {
      id: `temp-${Date.now()}`,
      role: "user",
      content,
      timestamp: Date.now() / 1000,
      phase: currentPhase,
    };
    setMessages((prev) => [...prev, optimisticMsg]);
    setIsLoading(true);

    try {
      const res = await sendMessage(sessionId, content);
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== optimisticMsg.id),
        res.user_message,
        res.assistant_message,
      ]);
      setCurrentPhase(res.current_phase);
      if (res.session_ended) {
        setSessionEnded(true);
        setShowPostModal(true);
      }
    } catch (err) {
      console.error("Failed to send message:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleNewSession = async () => {
    if (sessionId && !sessionEnded) {
      try { await endSession(sessionId); } catch { /* ignore */ }
    }
    setSessionId(null);
    setMessages([]);
    setCurrentPhase("CONVERSATION");
    setSessionEnded(false);
    setPreConviction(null);
    setShowPostModal(false);
    setCdsResult(null);
    setBotDisplayName("AI Assistant");
    setAssignedArm("sally_nepq");
    setSeconds(0);
    if (timerRef.current) clearInterval(timerRef.current);
    setShowSurvey(true);
  };

  const handleSwitchBot = async (newBot: BotArm) => {
    if (!sessionId || isLoading) return;

    try {
      setIsLoading(true);
      const res = await switchBot(sessionId, newBot);

      setSessionId(res.new_session_id);
      setCurrentPhase(res.current_phase);
      setBotDisplayName(res.bot_display_name);
      setAssignedArm(res.new_arm);

      setMessages((prev) => [
        ...prev,
        {
          id: `switch-${Date.now()}`,
          role: "assistant" as const,
          content: `--- Switched to ${res.bot_display_name} ---`,
          timestamp: Date.now() / 1000,
          phase: res.current_phase,
        },
        res.greeting,
      ]);
    } catch (err) {
      console.error("Failed to switch bot:", err);
      alert("Failed to switch bot. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetMemory = async () => {
    if (!confirm("This will clear all stored memory about you. Continue?")) return;
    try {
      await clearVisitorMemory();
      if (sessionId && !sessionEnded) {
        await endSession(sessionId);
      }
      setSessionId(null);
      setMessages([]);
      setCurrentPhase("CONVERSATION");
      setSessionEnded(false);
      setPreConviction(null);
      setShowPostModal(false);
      setCdsResult(null);
      setBotDisplayName("AI Assistant");
      setAssignedArm("sally_nepq");
      setSeconds(0);
      if (timerRef.current) clearInterval(timerRef.current);
      setShowSurvey(true);
      alert("Memory cleared. Starting fresh.");
    } catch (err) {
      console.error("Failed to reset memory:", err);
    }
  };

  return (
    <div className="h-screen flex flex-col bg-zinc-950 text-white">
      {/* Minimal header — no navigation */}
      <header className="h-14 border-b border-zinc-800 bg-zinc-950 flex items-center justify-center px-4">
        <span className="text-sm font-semibold text-white tracking-tight">
          100x AI Assistant
        </span>
      </header>

      {showSurvey && <ExperimentSurveyModal onStart={handleStartSession} />}

      {showPostModal && sessionId && (
        <PostConvictionModal
          sessionId={sessionId}
          preConviction={preConviction}
          onComplete={(result) => {
            setCdsResult(result);
            setShowPostModal(false);
          }}
        />
      )}

      {/* Landing screen — no session yet */}
      {!sessionId && !showSurvey && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <h2 className="text-lg font-semibold mb-2">AI Sales Assistant</h2>
            <p className="text-sm text-zinc-500 mb-6">
              Chat with an AI assistant about 100x Academy's AI Discovery Workshop
            </p>
            <button
              onClick={() => setShowSurvey(true)}
              className="h-10 px-6 rounded-md text-sm font-medium bg-white text-black hover:bg-zinc-200 transition-colors"
            >
              Start Conversation
            </button>
          </div>
        </div>
      )}

      {/* Active chat */}
      {sessionId && (
        <>
          {/* Minimal status bar — timer + bot switcher + reset */}
          <div className="flex items-center justify-end gap-3 px-4 py-2 border-b border-zinc-800 bg-zinc-950/80">
            <BotSwitcher
              currentArm={assignedArm}
              onSwitch={handleSwitchBot}
              disabled={isLoading || sessionEnded}
            />
            <button
              onClick={handleResetMemory}
              className="text-[10px] text-red-500/60 hover:text-red-400 transition-colors"
            >
              Reset Memory
            </button>
            <span
              className={`text-xs font-mono ${
                seconds > 1700 ? "text-red-400" : seconds > 1500 ? "text-amber-400" : "text-zinc-500"
              }`}
            >
              {formatTime(seconds)}
            </span>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-4">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} hidePhase />
            ))}
            {isLoading && (
              <div className="flex justify-start mb-3">
                <div className="bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-500">
                  Typing...
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <ChatInput
            onSend={handleSendMessage}
            disabled={isLoading || sessionEnded}
            sessionEnded={sessionEnded}
          />

          {sessionEnded && !showPostModal && (
            <div className="px-4 py-3 bg-zinc-900 border-t border-zinc-800 flex items-center justify-between">
              <span className="text-xs text-zinc-400">
                Chat ended. Thank you for participating!
              </span>
              {cdsResult && (
                <span className={`text-xs font-mono ${cdsResult.cds_score > 0 ? "text-emerald-400" : cdsResult.cds_score < 0 ? "text-red-400" : "text-zinc-500"}`}>
                  CDS: {cdsResult.cds_score > 0 ? "+" : ""}{cdsResult.cds_score}
                </span>
              )}
              <button
                onClick={handleNewSession}
                className="h-8 px-3 rounded-md text-xs font-medium bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
              >
                New Conversation
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
