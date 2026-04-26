import { useState } from "react";
import { useLocalParticipant } from "@livekit/components-react";

interface Props {
  onEnd: () => void;
}

export function CallControls({ onEnd }: Props) {
  const { localParticipant } = useLocalParticipant();
  const [muted, setMuted] = useState(false);

  const toggleMute = async () => {
    await localParticipant?.setMicrophoneEnabled(muted);
    setMuted(!muted);
  };

  return (
    <div className="flex gap-3 items-center">
      <button
        onClick={toggleMute}
        className="px-4 py-2 rounded-full bg-zinc-700 text-white text-sm hover:bg-zinc-600 transition-colors"
      >
        {muted ? "Unmute" : "Mute"}
      </button>
      <button
        onClick={onEnd}
        className="px-4 py-2 rounded-full bg-red-700 text-white text-sm hover:bg-red-600 transition-colors"
      >
        End Call
      </button>
    </div>
  );
}
