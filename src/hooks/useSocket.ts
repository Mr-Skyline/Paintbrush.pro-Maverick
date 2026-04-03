import { useEffect, useRef } from 'react';
import { io, Socket } from 'socket.io-client';

export function useTakeoffSocket(enabled: boolean) {
  const socketRef = useRef<Socket | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const socket = io({
      path: '/socket.io',
      transports: ['websocket', 'polling'],
    });
    socketRef.current = socket;
    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, [enabled]);
  return socketRef;
}
