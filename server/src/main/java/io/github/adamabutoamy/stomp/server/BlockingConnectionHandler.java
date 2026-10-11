package io.github.adamabutoamy.stomp.server;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.IOException;
import java.net.Socket;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import io.github.adamabutoamy.stomp.api.MessageEncoderDecoder;
import io.github.adamabutoamy.stomp.api.MessagingProtocol;
import io.github.adamabutoamy.stomp.protocol.ServerLog;

public class BlockingConnectionHandler<T> implements Runnable, ConnectionHandler<T> {
    // Java blocking sockets have no write timeout. Closing the socket releases a
    // blocked write. The watchdog never takes the write/protocol lock.
    private static final ScheduledThreadPoolExecutor DEADLINES = new ScheduledThreadPoolExecutor(1, task -> {
        Thread thread = new Thread(task, "stomp-write-deadlines");
        thread.setDaemon(true);
        return thread;
    });
    static { DEADLINES.setRemoveOnCancelPolicy(true); }
    private final MessagingProtocol<T> protocol;
    private final MessageEncoderDecoder<T> encdec;
    private final Socket sock;
    private final Object writeLock = new Object();
    private BufferedOutputStream out;
    private volatile boolean connected = true;
    private final int id;

    public BlockingConnectionHandler(Socket sock, MessageEncoderDecoder<T> reader, MessagingProtocol<T> protocol) {
        this.sock = sock;
        this.encdec = reader;
        this.protocol = protocol;
        this.id = ConnectionsImpl.getInstance().getID();
        ConnectionsImpl.getInstance().connect(id, this);
    }

    @Override
    public void run() {
        try (Socket socket = sock) {
            if (TransportLimits.SEND_BUFFER_BYTES > 0) socket.setSendBufferSize(TransportLimits.SEND_BUFFER_BYTES);
            BufferedInputStream in = new BufferedInputStream(socket.getInputStream());
            synchronized (writeLock) { out = new BufferedOutputStream(socket.getOutputStream()); }
            int read;
            while (!protocol.shouldTerminate() && connected && (read = in.read()) >= 0) {
                T message = encdec.decodeNextByte((byte) read);
                if (message == null || message.equals("")) continue;
                T response = protocol.process(message, id);
                if (response != null && !response.equals("")) {
                    // Both asynchronous broadcasts and direct replies share one lock.
                    send(response);
                    if (response.toString().startsWith("ERROR")) close();
                }
            }
        } catch (IllegalArgumentException ex) {
            ServerLog.event("WARN", "INPUT_REJECTED", id, "Frame limit or invalid input");
        } catch (IOException ex) {
            // Expected for peer resets and timeout-driven socket closure.
        } finally {
            connected = false;
            try { protocol.onDisconnect(id); }
            finally { ConnectionsImpl.getInstance().disconnect(id); }
        }
    }

    @Override
    public void close() throws IOException {
        connected = false;
        sock.close();
    }

    @Override
    public void send(T message) {
        if (message == null) return;
        synchronized (writeLock) {
            if (!connected || out == null) return;
            AtomicBoolean active = new AtomicBoolean(true);
            ScheduledFuture<?> deadline = DEADLINES.schedule(() -> {
                if (active.compareAndSet(true, false)) {
                    ServerLog.event("WARN", "WRITE_TIMEOUT", id, "Closing stalled subscriber");
                    try { close(); } catch (IOException ignored) {}
                }
            }, TransportLimits.WRITE_TIMEOUT_MILLIS, TimeUnit.MILLISECONDS);
            try {
                out.write(encdec.encode(message));
                out.flush();
            } catch (IOException ex) {
                try { close(); } catch (IOException ignored) {}
            } finally {
                active.set(false);
                deadline.cancel(false);
            }
        }
    }
}
