package io.github.adamabutoamy.stomp.server;

import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

public class ConnectionsImpl<T> implements Connections<T> {
    private static final ConnectionsImpl<?> instance = new ConnectionsImpl<>();
    private final ConcurrentHashMap<Integer, ConnectionHandler<T>> clients;
    private AtomicInteger connectionCount;

    private final ConcurrentHashMap<String, Set<Integer>> channels;
    public int getID(){
        return connectionCount.getAndIncrement();
    }

    private ConnectionsImpl() {
        this.clients = new ConcurrentHashMap<>();
        this.channels = new ConcurrentHashMap<>();
        this.connectionCount = new AtomicInteger(0);
    }
    public static ConnectionsImpl<?> getInstance() {
        return instance;
    }

    @Override
    public boolean send(int connectionId, T msg) {
        ConnectionHandler<T> client =  clients.get(connectionId);
        if(client != null){
            synchronized (client) {
                client.send(msg);
                return true;
            }
        }
        return false;
    }

    @Override
    public void send(String channel, T msg) {
        Set<Integer> topic = channels.get(channel);
        if(topic != null){
            synchronized (topic){
                for(int subscriber : topic){
                    this.send(subscriber, msg);
                }
            }
        }
    }

    @Override
    public void disconnect(int connectionId) {
        clients.remove(connectionId);
        // Remove from all channels
        for (Set<Integer> subs : channels.values()) {
            subs.remove((Integer) connectionId);
        }
    }

    public boolean unsubscribe(int connectionId, String channel) {
        Set<Integer> members = channels.get(channel);
        return members != null && members.remove(connectionId);
    }

    public boolean subscribe(int connectionId, String channel) {
        Set<Integer> candidate = ConcurrentHashMap.newKeySet();
        Set<Integer> existing = channels.putIfAbsent(channel, candidate);
        Set<Integer> members = existing == null ? candidate : existing;
        members.add(connectionId);
        return existing == null;
    }

    public void connect(int connectionId, ConnectionHandler<?> handler) {
        clients.put(connectionId, (ConnectionHandler<T>)handler);
    }
}
