package io.github.adamabutoamy.stomp.protocol;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

public class StompTopic {
    private String name;
    private ConcurrentHashMap<Integer, String> subscribers; // connectionId -> subscriptionId
    private AtomicInteger messageId;

    public StompTopic(String name) {
        this.name = name;
        this.subscribers = new ConcurrentHashMap<>();
        this.messageId = new AtomicInteger(0);
    }

    public void addSubscriber(int connectionId, String subscriptionId) {
        subscribers.put(connectionId, subscriptionId);
    }

    public void removeSubscriber(int connectionId) {
        subscribers.remove(connectionId);
    }

    public ConcurrentHashMap<Integer, String> getSubscribers() {
        return subscribers;
    }

    public int getNextMessageId() {
        return messageId.incrementAndGet();
    }

    public boolean hasSubscriber(int connectionId) {
        return subscribers.containsKey(connectionId);
    }

    public String getName() {
        return name;
    }
}