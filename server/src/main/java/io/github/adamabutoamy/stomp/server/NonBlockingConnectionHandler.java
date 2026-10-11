package io.github.adamabutoamy.stomp.server;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.SelectionKey;
import java.nio.channels.SocketChannel;
import java.util.Queue;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.ArrayBlockingQueue;
import io.github.adamabutoamy.stomp.protocol.ServerLog;
import java.util.concurrent.ConcurrentLinkedQueue;
import io.github.adamabutoamy.stomp.api.MessageEncoderDecoder;
import io.github.adamabutoamy.stomp.api.MessagingProtocol;

public class NonBlockingConnectionHandler<T> implements ConnectionHandler<T> {
    private static final int BUFFER_ALLOCATION_SIZE = 1 << 13;
    private static final ArrayBlockingQueue<ByteBuffer> BUFFER_POOL = new ArrayBlockingQueue<>(64);
    private final MessagingProtocol<T> protocol;
    private final MessageEncoderDecoder<T> encdec;
    private final Queue<ByteBuffer> writeQueue = new ConcurrentLinkedQueue<>();
    private final Object writeLock = new Object();
    private final SocketChannel chan;
    private final Reactor reactor;
    private final int id;
    private static final int MAX_PENDING_INPUT_BYTES = 131072;
    private final AtomicInteger pendingInputBytes = new AtomicInteger();
    private int queuedBytes;
    private volatile boolean closed;
    private volatile boolean closing;
    private volatile boolean readEnded;

    public NonBlockingConnectionHandler(MessageEncoderDecoder<T> reader,
            MessagingProtocol<T> protocol, SocketChannel chan, Reactor reactor) {
        this.chan = chan;
        this.encdec = reader;
        this.protocol = protocol;
        this.reactor = reactor;
        this.id = ConnectionsImpl.getInstance().getID();
        ConnectionsImpl.getInstance().connect(id, this);
    }

    public Runnable continueRead() {
        if (closed || closing || readEnded) return null;
        ByteBuffer buf = leaseBuffer();
        final int count;
        try {
            count = chan.read(buf);
        } catch (IOException ex) {
            releaseBuffer(buf);
            close();
            return null;
        }
        if (count == -1) {
            releaseBuffer(buf);
            readEnded = true;
            refreshInterest();
            // ActorThreadPool runs this after previously submitted input tasks.
            return this::finishInput;
        }
        if (count == 0) {
            releaseBuffer(buf);
            return null;
        }
        buf.flip();
        pendingInputBytes.addAndGet(count);
        refreshInterest();
        return () -> {
            try {
                // Cleanup cannot run halfway through a protocol operation.
                synchronized (protocol) {
                    while (buf.hasRemaining() && !closed && !closing) {
                        T message = encdec.decodeNextByte(buf.get());
                        if (message == null || message.equals("")) continue;
                        T response = protocol.process(message, id);
                        boolean terminate = protocol.shouldTerminate()
                                || (response != null && response.toString().startsWith("ERROR"));
                        synchronized (writeLock) {
                            if (closed) return;
                            if (terminate) closing = true;
                            if (response != null) {
                                if (!enqueue(response)) {
                                    reactor.executeOnActor(this, this::close);
                                    return;
                                }
                            }
                        }
                        // Includes a final ERROR/RECEIPT: close only after writing it.
                        if (terminate) finishInput();
                        else refreshInterest();
                    }
                }
            } catch (RuntimeException ex) {
                ServerLog.event("WARN", "INPUT_REJECTED", id, "Invalid or oversized input");
                close();
            } finally {
                releaseBuffer(buf);
                pendingInputBytes.addAndGet(-count);
                refreshInterest();
            }
        };
    }

    private void finishInput() {
        boolean empty;
        synchronized (writeLock) {
            if (closed) return;
            closing = true;
            empty = writeQueue.isEmpty();
        }
        if (empty) close();
        else refreshInterest();
    }

    public void close() {
        synchronized (writeLock) {
            if (closed) return;
            closed = true;
            closing = true;
            writeQueue.clear();
            queuedBytes = 0;
        }
        try {
            chan.close();
        } catch (IOException ex) {
            ex.printStackTrace();
        } finally {
            // Cleanup runs on this connection's actor. Never acquire a recipient's
            // protocol monitor from the sender actor or the selector thread.
            reactor.executeOnActor(this, () -> {
                try { synchronized (protocol) { protocol.onDisconnect(id); } }
                finally { ConnectionsImpl.getInstance().disconnect(id); }
            });
        }
    }

    public boolean isClosed() {
        return closed;
    }

    public void continueWrite() {
        boolean closeNow = false;
        try {
            synchronized (writeLock) {
                if (closed) return;
                int budget = 262144;
                while (!writeQueue.isEmpty() && budget > 0) {
                    ByteBuffer top = writeQueue.peek();
                    int limit = top.limit();
                    top.limit(top.position() + Math.min(top.remaining(), budget));
                    int written;
                    try { written = chan.write(top); } finally { top.limit(limit); }
                    queuedBytes -= written;
                    budget -= written;
                    if (top.hasRemaining()) break;
                    writeQueue.remove();
                }
                closeNow = closing && writeQueue.isEmpty();
            }
        } catch (IOException ex) {
            // Do not loop on the same failed write and block the selector.
            close();
            return;
        }
        if (closeNow) close();
        else refreshInterest();
    }

    // Evaluated on the selector thread, so queued updates use current state.
    int desiredInterestOps() {
        synchronized (writeLock) {
            if (closed) return 0;
            int ops = (closing || readEnded || pendingInputBytes.get() >= MAX_PENDING_INPUT_BYTES)
                    ? 0 : SelectionKey.OP_READ;
            if (!writeQueue.isEmpty()) ops |= SelectionKey.OP_WRITE;
            return ops;
        }
    }

    private void refreshInterest() {
        reactor.updateInterestedOps(chan, desiredInterestOps());
    }

    private static ByteBuffer leaseBuffer() {
        ByteBuffer buffer = BUFFER_POOL.poll();
        if (buffer == null) return ByteBuffer.allocateDirect(BUFFER_ALLOCATION_SIZE);
        buffer.clear();
        return buffer;
    }

    private static void releaseBuffer(ByteBuffer buffer) {
        BUFFER_POOL.offer(buffer);
    }

    // Called only with writeLock held. Account for bytes remaining, not frame count.
    private boolean enqueue(T message) {
        byte[] encoded = encdec.encode(message);
        if ((long) queuedBytes + encoded.length > TransportLimits.MAX_QUEUED_BYTES) {
            closing = true;
            ServerLog.event("WARN", "SLOW_CONSUMER", id, "Output byte limit exceeded");
            return false;
        }
        writeQueue.add(ByteBuffer.wrap(encoded));
        queuedBytes += encoded.length;
        return true;
    }

    @Override
    public void send(T message) {
        if (message == null) return;
        boolean accepted;
        synchronized (writeLock) {
            if (closed || closing) return;
            accepted = enqueue(message);
        }
        if (!accepted) reactor.executeOnActor(this, this::close);
        else refreshInterest();
    }
}
