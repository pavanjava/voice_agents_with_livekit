import { AccessToken } from "livekit-server-sdk";
import http from "http";

const API_KEY = "devkey";
const API_SECRET = "secret";
const LIVEKIT_URL = "ws://localhost:7880";

const server = http.createServer(async (req, res) => {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");

    if (req.method === "OPTIONS") {
        res.writeHead(204);
        res.end();
        return;
    }

    if (req.url === "/token" && req.method === "GET") {
        const identity = `user-${Date.now()}`;
        const roomName = "voice-room";

        const at = new AccessToken(API_KEY, API_SECRET, {
            identity,
            ttl: "1h",
        });

        at.addGrant({
            roomJoin: true,
            room: roomName,
            canPublish: true,
            canSubscribe: true,
        });

        const token = await at.toJwt();

        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ token, url: LIVEKIT_URL, roomName, identity }));
        return;
    }

    res.writeHead(404);
    res.end();
});

server.listen(3001, () => {
    console.log("Token server running at http://localhost:3001");
});