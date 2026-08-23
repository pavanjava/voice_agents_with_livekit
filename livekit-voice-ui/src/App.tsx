import { useState, useCallback, useRef } from "react";
import {
    Room,
    RoomEvent,
    RemoteTrack,
    Track,
    createLocalAudioTrack,
} from "livekit-client";
import "./App.css";

type Status = "idle" | "connecting" | "connected" | "disconnected";

export default function App() {
    const [status, setStatus] = useState<Status>("idle");
    const roomRef = useRef<Room | null>(null);
    const isConnectingRef = useRef(false);

    const connect = useCallback(async () => {
        if (isConnectingRef.current || roomRef.current) return;
        isConnectingRef.current = true;
        setStatus("connecting");

        try {
            console.log("connect() called, fetching token...");  // ← add this
            const res = await fetch("http://localhost:3001/token");

            const { token, url } = await res.json();

            const room = new Room();
            roomRef.current = room;

            room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
                if (track.kind === Track.Kind.Audio) {
                    track.attach();
                }
            });

            room.on(RoomEvent.Disconnected, () => {
                roomRef.current = null;
                isConnectingRef.current = false;
                setStatus("idle");
            });

            await room.connect(url, token);
            const audioTrack = await createLocalAudioTrack();
            await room.localParticipant.publishTrack(audioTrack);
            setStatus("connected");
        } catch (e) {
            console.error("Connection failed:", e);
            roomRef.current = null;
            isConnectingRef.current = false;
            setStatus("idle");
        } finally {
            isConnectingRef.current = false;
        }
    }, []);

    const disconnect = useCallback(async () => {
        await roomRef.current?.disconnect();
        roomRef.current = null;
        setStatus("idle");
    }, []);

    const isConnected = status === "connected";
    const isConnecting = status === "connecting";

    return (
        <div className="app">
            <h1>Voice Agent</h1>
            <p className="status">{statusLabel(status)}</p>

            <button
                className={`mic-button ${isConnected ? "active" : ""} ${isConnecting ? "connecting" : ""}`}
                onClick={isConnected ? disconnect : connect}
                disabled={isConnecting}
            >
                <svg viewBox="0 0 24 24" fill="currentColor" width="40" height="40">
                    <path d="M12 1a4 4 0 0 1 4 4v6a4 4 0 0 1-8 0V5a4 4 0 0 1 4-4zm0 2a2 2 0 0 0-2 2v6a2 2 0 0 0 4 0V5a2 2 0 0 0-2-2zm6.5 6.5A6.5 6.5 0 0 1 12 14a6.5 6.5 0 0 1-6.5-4.5H4a8 8 0 0 0 7 7.93V20H9v2h6v-2h-2v-2.07A8 8 0 0 0 20 9.5h-1.5z" />
                </svg>
            </button>

            <p className="hint">
                {isConnected ? "Click to end conversation" : "Click to start talking"}
            </p>
        </div>
    );
}

function statusLabel(status: Status): string {
    switch (status) {
        case "idle": return "Ready";
        case "connecting": return "Connecting…";
        case "connected": return "Listening";
        case "disconnected": return "Disconnected";
    }
}