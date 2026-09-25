package bgu.spl.net.impl.stomp;

import bgu.spl.net.api.MessageEncoderDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

public class StompEndec implements MessageEncoderDecoder<String> {
    private byte[] bytes = new byte[1 << 10];
    private int len = 0;

    @Override
    public String decodeNextByte(byte nextByte) {
        if (nextByte == '\u0000') {
            String result = new String(bytes, 0, len, StandardCharsets.UTF_8);
            len = 0;
            return result;
        }

        pushByte(nextByte);
        return null;
    }

    @Override
    public byte[] encode(String message) {
        return message.getBytes(StandardCharsets.UTF_8);
    }

    private void pushByte(byte nextByte) {
        if (len >= bytes.length) {
            bytes = Arrays.copyOf(bytes, bytes.length * 2);
        }
        bytes[len++] = nextByte;
    }
}
