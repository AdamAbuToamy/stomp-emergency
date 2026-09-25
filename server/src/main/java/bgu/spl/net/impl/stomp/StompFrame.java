package bgu.spl.net.impl.stomp;

import java.util.HashMap;

public class StompFrame {
    private String command;
    private final HashMap<String, String> headers;//the header and the value for it
    private String body;

    public StompFrame(String command) {
        this.command = command;
        this.headers = new HashMap<>();
        this.body = "";
    }

    private void addHeader(String key, String value) {
        headers.put(key.trim(), value.trim());
    }

    private void setBody(String body) {
        this.body = body != null ? body : "";
    }

    public String getCommand() {
        return command;
    }

    public String getHeader(String key) {
        return headers.get(key);
    }

    public String getBody() {
        return body;
    }

    public boolean hasHeader(String key) {
        return headers.containsKey(key);
    }

    public static StompFrame createErrorFrame(String message, String receiptId) {
        StompFrame frame = new StompFrame("ERROR");
        frame.addHeader("message", message);
        if (receiptId != null) {
            frame.addHeader("receipt-id", receiptId);
        }
        return frame;
    }

    public static StompFrame createReceiptFrame(String receiptId) {
        StompFrame frame = new StompFrame("RECEIPT");
        frame.addHeader("receipt-id", receiptId);
        return frame;
    }

    public static StompFrame createMessageFrame(String subscription, String messageId,
                                                String destination, String body) {
        StompFrame frame = new StompFrame("MESSAGE");
        frame.addHeader("subscription", subscription);
        frame.addHeader("message-id", messageId);
        frame.addHeader("destination", destination);
        frame.setBody(body);
        return frame;
    }

    @Override
    public String toString() {
        StringBuilder frame = new StringBuilder(command + "\n");

        // Add headers
        for (HashMap.Entry<String, String> header : headers.entrySet()) {
            frame.append(header.getKey()).append(":").append(header.getValue()).append("\n");
        }

        // Add blank line and body
        frame.append("\n").append(body).append("\u0000");

        return frame.toString();
    }

    public static StompFrame parse(String rawFrame) {
        if (rawFrame == null || rawFrame.isEmpty()) {
            throw new IllegalArgumentException("Empty frame");
        }

        String[] parts = rawFrame.split("\n\n", 2);//separate the body and the command + header
        StompFrame frame = getFrame(parts[0]);

        // Parse body if exists
        if (parts.length > 1) {
            frame.setBody(parts[1].replace("\u0000", ""));
        }

        return frame;
    }

    private static StompFrame getFrame(String parts) {
        String[] headerPart = parts.split("\n");

        if (headerPart.length == 0) {
            throw new IllegalArgumentException("No command found");
        }

        // Parse command
        StompFrame frame = new StompFrame(headerPart[0].trim());

        // Parse headers
        for (int i = 1; i < headerPart.length; i++) {
            String[] header = headerPart[i].split(":", 2);
            if (header.length == 2) {
                frame.addHeader(header[0], header[1]);
            }
        }
        return frame;
    }
}
