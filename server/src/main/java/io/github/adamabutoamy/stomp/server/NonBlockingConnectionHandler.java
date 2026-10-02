package io.github.adamabutoamy.stomp.server;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.SelectionKey;
import java.nio.channels.SocketChannel;
import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;
import io.github.adamabutoamy.stomp.api.MessageEncoderDecoder;
import io.github.adamabutoamy.stomp.api.MessagingProtocol;

public class NonBlockingConnectionHandler<T> implements ConnectionHandler<T> {
    private static final int BUFFER_ALLOCATION_SIZE = 1 << 13;
    private static final ConcurrentLinkedQueue<ByteBuffer> BUFFER_POOL = new ConcurrentLinkedQueue<>();
    private final MessagingProtocol<T> protocol;
    private final MessageEncoderDecoder<T> encdec;
    private final Queue<ByteBuffer> writeQueue = new ConcurrentLinkedQueue<>();
    private final Object writeLock = new Object();
    private final SocketChannel chan;
    private final Reactor reactor;
    private final int id;
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
                                writeQueue.add(ByteBuffer.wrap(encdec.encode(response)));
                            }
                        }
                        // Includes a final ERROR/RECEIPT: close only after writing it.
                        if (terminate) finishInput();
                        else refreshInterest();
                    }
                }
            } catch (RuntimeException ex) {
                close();
                throw ex;
            } finally {
                releaseBuffer(buf);
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
        }
        try {
            chan.close();
        } catch (IOException ex) {
            ex.printStackTrace();
        } finally {
            try {
                synchronized (protocol) {
                    protocol.onDisconnect(id);
                }
            } finally {
                ConnectionsImpl.getInstance().disconnect(id);
            }
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
                while (!writeQueue.isEmpty()) {
                    ByteBuffer top = writeQueue.peek();
                    chan.write(top);
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
            int ops = (closing || readEnded) ? 0 : SelectionKey.OP_READ;
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
        BUFFER_POOL.add(buffer);
    }

    @Override
    public void send(T message) {
        if (message == null) return;
        synchronized (writeLock) {
            if (closed || closing) return;
            writeQueue.add(ByteBuffer.wrap(encdec.encode(message)));
        }
        refreshInterest();
    }
}
