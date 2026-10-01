package bgu.spl.net.impl.stomp;

import java.util.HashMap;
import java.util.concurrent.ConcurrentHashMap;

import bgu.spl.net.api.MessagingProtocol;
import bgu.spl.net.srv.Connections;
import bgu.spl.net.srv.ConnectionsImpl;

public class StompMessagingProtocol implements MessagingProtocol<String> {
    // One shared lock: each connection has its own protocol instance.
    private static final Object AUTH_LOCK = new Object();

    private static final ConcurrentHashMap<String, StompTopic> topics = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, String> userPasswords = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<Integer, String> connectedUsers = new ConcurrentHashMap<>();

    private ConnectionsImpl<String> connections = (ConnectionsImpl<String>) ConnectionsImpl.getInstance();
    private boolean shouldTerminate = false;
    private HashMap<Integer,HashMap<String, String>> subscriptions = new HashMap<>(); // subscriptionId -> topic

    private String handleConnect(StompFrame frame, int connectionId) {
        synchronized (AUTH_LOCK) {
            return authenticateUnderLock(frame, connectionId);
        }
    }

    // Called only while holding AUTH_LOCK; no socket I/O occurs here.
    private String authenticateUnderLock(StompFrame frame, int connectionId) {
        if (connectedUsers.containsKey(connectionId)) {
            return createErrorFrame(
                    "Connection already authenticated",
                    frame.getHeader("receipt"),
                    connectionId
            );
        }

        // Check required headers
        String acceptVersion = frame.getHeader("accept-version");
        String host = frame.getHeader("host");
        String login = frame.getHeader("login");
        String passcode = frame.getHeader("passcode");

        // Validate all required headers exist
        if (acceptVersion == null || host == null || login == null || passcode == null) {
            return createErrorFrame("Missing required headers", null, connectionId);
        }

        // Validate version
        if (!acceptVersion.equals("1.2")) {
            return createErrorFrame("Version not supported", null, connectionId);
        }

        // Validate host
        if (!host.trim().equals("stomp.cs.bgu.ac.il")) {
            return createErrorFrame("Invalid host", null, connectionId);
        }

        // Check if user is already logged in
        if (connectedUsers.containsValue(login)) {
            return createErrorFrame("User already logged in", null, connectionId);
        }

        // Check password if user exists
        if (userPasswords.containsKey(login)) {
            if (!userPasswords.get(login).equals(passcode)) {
                return createErrorFrame("Wrong password", null, connectionId);
            }
        } else {
            // New user - store credentials
            userPasswords.put(login, passcode);
        }

        // Connect user
        connectedUsers.put(connectionId, login);
        // Return CONNECTED frame
        return "CONNECTED\n" +
                "version:1.2\n" +
                "\n" +
                "\u0000";
    }

    private String handleSubscribe(StompFrame frame, int connectionId) {
        String destination = frame.getHeader("destination");
        String id = frame.getHeader("id");

        if (destination == null || id == null) {
            return createErrorFrame("Missing headers", null, connectionId);
        }
        HashMap<String, String> userSubscriptions =
                subscriptions.get(connectionId);

        if (userSubscriptions != null && userSubscriptions.containsKey(id)) {
            return createErrorFrame(
                    "Subscription id already in use",
                    frame.getHeader("receipt"),
                    connectionId
            );
        }

        StompTopic topic =
                topics.computeIfAbsent(destination, StompTopic::new);
        topic.addSubscriber(connectionId, id);
        connections.subscribe(connectionId, destination);
        subscriptions.computeIfAbsent(connectionId, key -> new HashMap<>())
                .put(id, destination);

        String receipt = frame.getHeader("receipt");
        return receipt != null ?
                "RECEIPT\nreceipt-id:" + receipt + "\n\n\u0000" : null;
    }

    private String handleUnsubscribe(StompFrame frame, int connectionId) {
        String id = frame.getHeader("id");

        if (id == null) {
            return createErrorFrame("Missing id header", null,connectionId);
        }

        String topicName = subscriptions.get(connectionId).remove(id);
        if (topicName != null) {
            StompTopic topic = topics.get(topicName);
            if (topic != null) {
                topic.removeSubscriber(connectionId);
                connections.unsubscribe(connectionId,topicName);
            }
        }

        String receipt = frame.getHeader("receipt");
        return receipt != null ?
                "RECEIPT\nreceipt-id:" + receipt + "\n\n\u0000" : null;
    }

    private String handleSend(StompFrame frame, int connectionId) {
        String destination = frame.getHeader("destination");

        if (destination == null) {
            return createErrorFrame("Missing destination header", frame.getHeader("receipt"),connectionId);
        }

        StompTopic topic = topics.get(destination);
        if (topic == null || !topic.hasSubscriber(connectionId)) {
            return createErrorFrame("Client is not subscribed to topic: " + destination,
                    frame.getHeader("receipt"), connectionId);
        }

        int messageId = topic.getNextMessageId();
        for (var subscriber : topic.getSubscribers().entrySet()) {
            int recipientConnectionId = subscriber.getKey();
            String recipientSubscriptionId = subscriber.getValue();

            String message = StompFrame.createMessageFrame(
                    recipientSubscriptionId,
                    String.valueOf(messageId),
                    destination,
                    frame.getBody()
            ).toString();

            connections.send(recipientConnectionId, message);
        }
        // Send receipt if requested
        String receipt = frame.getHeader("receipt");

        return receipt != null ?
                StompFrame.createReceiptFrame(receipt).toString() : null;
    }

    private String handleDisconnect(StompFrame frame, int connectionId) {
        String receipt = frame.getHeader("receipt");
        if (receipt == null) {
            return createErrorFrame("Missing receipt header", null, connectionId);
        }

        onDisconnect(connectionId);
        return "RECEIPT\nreceipt-id:" + receipt + "\n\n\u0000";
    }

    @Override
    public void onDisconnect(int connectionId) {
        HashMap<String, String> userSubscriptions =
                subscriptions.remove(connectionId);

        if (userSubscriptions != null) {
            for (String topicName : userSubscriptions.values()) {
                StompTopic topic = topics.get(topicName);
                if (topic != null) {
                    topic.removeSubscriber(connectionId);
                }
                connections.unsubscribe(connectionId, topicName);
            }
        }

        synchronized (AUTH_LOCK) {
            connectedUsers.remove(connectionId);
        }
        shouldTerminate = true;
    }

    private String createErrorFrame(String message, String receiptId, int connectionId) {
        synchronized (AUTH_LOCK) {
            connectedUsers.remove(connectionId);
        }
        return StompFrame.createErrorFrame(message, receiptId).toString();
    }

    @Override
    public void start(int connectionId, Connections<String> connections) {
    }

    @Override
    public String process(String message, int idOfSender) {
        try {
            StompFrame frame = StompFrame.parse(message);

            if (!"CONNECT".equals(frame.getCommand())
                    && !connectedUsers.containsKey(idOfSender)) {
                return createErrorFrame("Login required", null, idOfSender);
            }

            switch (frame.getCommand()) {
                case "CONNECT":
                    return handleConnect(frame,idOfSender);
                case "SUBSCRIBE":
                    return handleSubscribe(frame,idOfSender);
                case "UNSUBSCRIBE":
                    return handleUnsubscribe(frame,idOfSender);
                case "SEND":
                    return handleSend(frame,idOfSender);
                case "DISCONNECT":
                    return handleDisconnect(frame,idOfSender);
                default:
                    return createErrorFrame("Invalid command", null,idOfSender);
            }
        } catch (Exception e) {
            return createErrorFrame("Malformed frame", null,idOfSender);
        }
    }

    @Override
    public boolean shouldTerminate() {
        return shouldTerminate;
    }
}