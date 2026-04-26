import { useEffect, useState } from "react";
import {
  useTracks,
  useLocalParticipant,
} from "@livekit/components-react";
import { Track } from "livekit-client";

const SMOOTHING = 0.7;

function wireAudioMeter(
  track: MediaStreamTrack,
  setLevel: (l: number) => void
): () => void {
  const ctx = new AudioContext();
  const stream = new MediaStream([track]);
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 256;
  analyser.smoothingTimeConstant = SMOOTHING;
  source.connect(analyser);

  const data = new Uint8Array(analyser.frequencyBinCount);
  let raf = 0;

  const tick = () => {
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sum += v * v;
    }
    setLevel(Math.sqrt(sum / data.length));
    raf = requestAnimationFrame(tick);
  };
  tick();

  return () => {
    cancelAnimationFrame(raf);
    source.disconnect();
    ctx.close();
  };
}

export function VoiceBubble() {
  const { localParticipant } = useLocalParticipant();
  const remoteTracks = useTracks([Track.Source.Microphone], {
    onlySubscribed: true,
  });
  const [agentLevel, setAgentLevel] = useState(0);
  const [userLevel, setUserLevel] = useState(0);

  // Subscribe to agent (remote) audio
  useEffect(() => {
    const agentPub = remoteTracks.find(
      (t) => t.participant.identity !== localParticipant?.identity
    )?.publication;
    const msTrack = (agentPub?.track as any)?.mediaStreamTrack as
      | MediaStreamTrack
      | undefined;
    if (!msTrack) return;
    return wireAudioMeter(msTrack, setAgentLevel);
  }, [remoteTracks, localParticipant]);

  // Subscribe to user (local) mic
  useEffect(() => {
    const pub = localParticipant?.getTrackPublication(Track.Source.Microphone);
    const msTrack = (pub?.track as any)?.mediaStreamTrack as
      | MediaStreamTrack
      | undefined;
    if (!msTrack) return;
    return wireAudioMeter(msTrack, setUserLevel);
  }, [localParticipant]);

  const agentSpeaking = agentLevel > 0.05;
  const userSpeaking = userLevel > 0.05 && userLevel > agentLevel;
  const dominant = Math.max(agentLevel, userLevel);
  const scale = 1 + dominant * 0.4;
  const glow = 20 + dominant * 60;

  const bg = userSpeaking
    ? "bg-cyan-500"
    : agentSpeaking
    ? "bg-orange-400"
    : "bg-zinc-700";

  return (
    <div className="flex items-center justify-center w-64 h-64 relative">
      <div
        className={`absolute rounded-full transition-colors duration-300 ${bg}`}
        style={{
          width: "60%",
          height: "60%",
          transform: `scale(${scale})`,
          transition: "transform 80ms linear",
          boxShadow: `0 0 ${Math.round(glow)}px rgba(255,255,255,0.3)`,
        }}
      />
    </div>
  );
}
