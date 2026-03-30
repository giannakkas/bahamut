"use client";
import { useEffect, useRef, useState, useCallback } from "react";

/**
 * useAdminSocket — connects to /ws/admin/live for real-time dashboard updates.
 *
 * Returns:
 *   status: "connected" | "connecting" | "disconnected"
 *   lastEvent: { event, data, ts } | null
 *   
 * On events like cycle_completed, position_opened, position_closed,
 * the parent component can trigger a data refetch.
 */

type WsStatus = "connected" | "connecting" | "disconnected";
type WsEvent = { event: string; data: any; ts: string };

export function useAdminSocket(onEvent?: (evt: WsEvent) => void) {
  const [status, setStatus] = useState<WsStatus>("disconnected");
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const pingRef = useRef<NodeJS.Timeout | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    // Get token from localStorage (set by login)
    const token = typeof window !== "undefined" ? localStorage.getItem("bahamut_token") : null;
    if (!token) {
      setStatus("disconnected");
      return;
    }

    // Build WS URL from API base
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";
    const wsBase = apiUrl.replace(/^http/, "ws").replace(/\/+$/, "");
    const url = `${wsBase}/ws/admin/live?token=${token}`;

    setStatus("connecting");
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      retryRef.current = 0;
      // Start ping keepalive every 30s
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ event: "ping" }));
        }
      }, 30000);
    };

    ws.onmessage = (e) => {
      try {
        const msg: WsEvent = JSON.parse(e.data);
        if (msg.event === "pong") return; // Ignore keepalive responses
        setLastEvent(msg);
        onEventRef.current?.(msg);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      setStatus("disconnected");
      if (pingRef.current) clearInterval(pingRef.current);
      // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
      const delay = Math.min(30000, 1000 * Math.pow(2, retryRef.current));
      retryRef.current++;
      timerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (timerRef.current) clearTimeout(timerRef.current);
      if (pingRef.current) clearInterval(pingRef.current);
    };
  }, [connect]);

  return { status, lastEvent };
}
