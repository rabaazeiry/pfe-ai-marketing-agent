import { io, Socket } from 'socket.io-client';
import { useAuthStore } from '@/stores/auth.store';

let socket: Socket | null = null;

export function getSocket(): Socket {
  if (socket && socket.connected) return socket;
  const token = useAuthStore.getState().token;
  const url = import.meta.env.VITE_WS_URL || window.location.origin;

  socket = io(url, {
    auth: { token },
    withCredentials: true,
    transports: ['websocket', 'polling'],
    autoConnect: true,
    reconnection: true,
    reconnectionAttempts: 10,
    reconnectionDelay: 1000
  });

  socket.on('connect', () => console.log('[ws] connected', socket?.id));
  socket.on('connect_error', (err) => console.warn('[ws] error', err.message));
  socket.on('disconnect', (reason) => console.log('[ws] disconnected', reason));

  return socket;
}

export function closeSocket() {
  socket?.disconnect();
  socket = null;
}
