import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { LiveKitRoom } from "@livekit/components-react";
import "@livekit/components-styles";
import type { Room } from "livekit-client";
import { ArmPicker } from "../../components/voice/ArmPicker";
import { VoiceBubble } from "../../components/voice/VoiceBubble";
import { CallControls } from "../../components/voice/CallControls";
import { ReasoningPanel } from "../../components/voice/ReasoningPanel";
import { RoomBridge } from "../../components/voice/RoomBridge";
import { mintLiveKitToken } from "../../lib/voiceApi";

type CallState = "idle" | "connecting" | "active" | "ended";

export function VoicePage() {
  const [callState, setCallState] = useState<CallState>("idle");
  const [token, setToken] = useState<string | null>(null);
  const [lkUrl, setLkUrl] = useState<string | null>(null);
  const [callId, setCallId] = useState<string | null>(null);
  const [forcedArm, setForcedArm] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Lifted from <LiveKitRoom> via <RoomBridge> so the sibling <ReasoningPanel>
  // can subscribe to the data channel (Phase 2 live mode).
  const [room, setRoom] = useState<Room | null>(null);

  const handleRoomReady = useCallback((r: Room | null) => {
    setRoom(r);
  }, []);

  const startCall = async () => {
    setCallState("connecting");
    setError(null);
    try {
      const data = await mintLiveKitToken(forcedArm);
      setToken(data.token);
      setLkUrl(data.url);
      setCallId(data.callId);
      setCallState("active");
    } catch (e: any) {
      setError(e.message || "Failed to start call");
      setCallState("idle");
    }
  };

  const endCall = () => {
    setCallState("ended");
    setToken(null);
    // keep callId so we can link to the session detail page
  };

  const resetCall = () => {
    setCallState("idle");
    setToken(null);
    setLkUrl(null);
    setCallId(null);
    setError(null);
  };

  return (
    <div className="flex h-[calc(100vh-56px)]">
      {/* Main call area */}
      <div className="flex-1 flex flex-col items-center justify-center gap-6 p-8">
        {callState === "idle" && (
          <>
            <ArmPicker selected={forcedArm} onChange={setForcedArm} />
            {error && (
              <p className="text-red-400 text-sm">{error}</p>
            )}
            <button
              onClick={startCall}
              className="px-8 py-4 rounded-full bg-blue-600 text-white text-base font-medium hover:bg-blue-500 transition-colors"
            >
              Talk to Sally
            </button>
          </>
        )}

        {callState === "connecting" && (
          <p className="text-zinc-400 text-sm">Connecting…</p>
        )}

        {callState === "active" && token && lkUrl && (
          <LiveKitRoom
            token={token}
            serverUrl={lkUrl}
            connect={true}
            audio={true}
            onDisconnected={endCall}
            className="flex flex-col items-center gap-6"
          >
            <RoomBridge onRoomReady={handleRoomReady} />
            <VoiceBubble />
            <CallControls onEnd={endCall} />
          </LiveKitRoom>
        )}

        {callState === "ended" && (
          <div className="flex flex-col items-center gap-4 text-center">
            <p className="text-zinc-400">Call ended.</p>
            {callId && (
              <Link
                to={`/voice/sessions/${callId}`}
                className="text-blue-400 hover:text-blue-300 underline text-sm"
              >
                View transcript &amp; reasoning
              </Link>
            )}
            <button
              onClick={resetCall}
              className="px-5 py-2 rounded-md bg-zinc-800 text-zinc-300 text-sm hover:bg-zinc-700 transition-colors"
            >
              Start another call
            </button>
          </div>
        )}
      </div>

      {/* Reasoning panel sidebar */}
      <aside className="w-80 border-l border-zinc-800 overflow-y-auto shrink-0">
        <ReasoningPanel
          callId={callId}
          live={callState === "active" || callState === "connecting"}
          room={room}
        />
      </aside>
    </div>
  );
}
