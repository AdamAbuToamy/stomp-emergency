package bgu.spl.net.srv;

import java.util.LinkedList;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

public class ConnectionsImpl<T> implements Connections<T> {
    private static final ConnectionsImpl<?> instance = new ConnectionsImpl<>();
    private final ConcurrentHashMap<Integer, ConnectionHandler<T>> clients;
    private AtomicInteger connectionCount;

    private final ConcurrentHashMap<String, LinkedList<Integer>> channels;
    public int getID(){
        return connectionCount.getAndIncrement();
    }

    private ConnectionsImpl() {
        this.clients = new ConcurrentHashMap<>();
        this.channels = new ConcurrentHashMap<>();
        this.connectionCount = new AtomicInteger(0);
    }
    private void addChannel(String channel){
        channels.putIfAbsent(channel,new LinkedList<>());
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
        LinkedList<Integer> topic = channels.get(channel);
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
        for (LinkedList<Integer> subs : channels.values()) {
            subs.remove((Integer) connectionId);
        }
    }

    public boolean unsubscribe(int connectionId, String channel){
        return channels.get(channel).remove((Integer) connectionId);
    }
    public boolean subscribe(int connectionId,String channel){

        boolean didAddChannel = false;
        if(!channels.containsKey(channel)){
            addChannel(channel);
            didAddChannel = true;
        }

        channels.get(channel).addLast(connectionId);

        return didAddChannel;
    }

    public void connect(int connectionId, ConnectionHandler<?> handler) {
        clients.put(connectionId, (ConnectionHandler<T>)handler);
    }
}
