package io.github.adamabutoamy.stomp.api;

import io.github.adamabutoamy.stomp.server.Connections;

public interface MessagingProtocol<T> {
    
    void start(int connectionId, Connections<T> connections);


    /**
     * process the given message 
     * @param msg the received message
     * @return the response to send or null if no response is expected by the client
     */
    T process(T msg,int idOfSender);
 
    /**
     * @return true if the connection should be terminated
     */
    boolean shouldTerminate();

    /** Called when the underlying connection ends. Safe to call more than once. */
    default void onDisconnect(int connectionId) {
        // Protocols without connection-specific state need no cleanup.
    }
 
}