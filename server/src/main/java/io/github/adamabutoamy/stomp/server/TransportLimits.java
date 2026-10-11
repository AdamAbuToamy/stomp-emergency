package io.github.adamabutoamy.stomp.server;

/** Per-connection policy, overridable with JVM -D options for deterministic tests. */
public final class TransportLimits {
    public static final int MAX_FRAME_BYTES = positive("stomp.maxFrameBytes", 262144);
    public static final int MAX_QUEUED_BYTES = positive("stomp.maxQueuedBytes", 4194304);
    public static final int WRITE_TIMEOUT_MILLIS = positive("stomp.writeTimeoutMillis", 2000);
    public static final int SEND_BUFFER_BYTES = Integer.getInteger("stomp.sendBufferBytes", 0);
    private TransportLimits() {}
    private static int positive(String key, int fallback) {
        int value = Integer.getInteger(key, fallback);
        if (value <= 0) throw new IllegalArgumentException(key + " must be positive");
        return value;
    }
}
