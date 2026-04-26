import { useEffect } from "react";
import { useMaybeRoomContext } from "@livekit/components-react";
import type { Room } from "livekit-client";

/**
 * Tiny child of <LiveKitRoom> whose only job is to read the Room from
 * RoomContext and lift it into the parent's state via onRoomReady.
 *
 * Required because Phase 1 placed <ReasoningPanel> as a sibling of
 * <LiveKitRoom>, not inside it. The panel needs the Room to subscribe
 * to data channel events but can't call useRoomContext() from outside
 * the room boundary.
 */
interface Props {
  onRoomReady: (room: Room | null) => void;
}

export function RoomBridge({ onRoomReady }: Props) {
  const room = useMaybeRoomContext();

  useEffect(() => {
    onRoomReady(room ?? null);
    return () => {
      onRoomReady(null);
    };
  }, [room, onRoomReady]);

  return null;
}
