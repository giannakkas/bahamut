"use client";
import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from "react";

type WsStatus = "connected" | "connecting" | "disconnected";
type WsEvent = { event: string; data: any; ts: string };
type WsListener = (evt: WsEvent) => void;

interface AdminSocketContextType {
  status: WsStatus;
  lastEvent: WsEvent | null;
  addListener: (fn: WsListener) => void;
  removeListener: (fn: WsListener) => void;
}

const AdminSocketContext = createContext<AdminSocketContextType>({
  status: "disconnected",
  lastEvent: null,
  addListener: () => {},
  removeListener: () => {},
});

export function useAdminSocket() {
  return useContext(AdminSocketContext);
}

export function AdminSocketProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<WsStatus>("disconnected");
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const pingRef = useRef<NodeJS.Timeout | null>(null);
  const listenersRef = useRef<Set<WsListener>>(new Set());

  const addListener = useCallback((fn: WsListener) => { listenersRef.current.add(fn); }, []);
  const removeListener = useCallback((fn: WsListener) => { listenersRef.current.delete(fn); }, []);

  const connect = useCallback(() => {
    const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;
    if (!token) {
      timerRef.current = setTimeout(connect, 2000);
      return;
    }

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";
    if (!apiUrl) return;
    const wsBase = apiUrl.replace(/^http/, "ws").replace(/\/+$/, "");
    const url = `${wsBase}/ws/admin/live?token=${encodeURIComponent(token)}`;

    setStatus("connecting");
    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("connected");
        retryRef.current = 0;
        pingRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ event: "ping" }));
          }
        }, 30000);
      };

      ws.onmessage = (e) => {
        try {
          const msg: WsEvent = JSON.parse(e.data);
          if (msg.event === "pong") return;
          setLastEvent(msg);
          listenersRef.current.forEach((fn) => { try { fn(msg); } catch {} });
        } catch {}
      };

      ws.onclose = () => {
        setStatus("disconnected");
        if (pingRef.current) clearInterval(pingRef.current);
        const delay = Math.min(30000, 1000 * Math.pow(2, retryRef.current));
        retryRef.current++;
        timerRef.current = setTimeout(connect, delay);
      };

      ws.onerror = () => { ws.close(); };
    } catch {
      const delay = Math.min(30000, 1000 * Math.pow(2, retryRef.current));
      retryRef.current++;
      timerRef.current = setTimeout(connect, delay);
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (timerRef.current) clearTimeout(timerRef.current);
      if (pingRef.current) clearInterval(pingRef.current);
    };
  }, [connect]);

  return (
    <AdminSocketContext.Provider value={{ status, lastEvent, addListener, removeListener }}>
      {children}
    </AdminSocketContext.Provider>
  );
}
