package bgu.spl.net.impl.rci;

import bgu.spl.net.api.MessagingProtocol;
import bgu.spl.net.srv.Connections;

import java.io.Serializable;

public class RemoteCommandInvocationProtocol<T> implements MessagingProtocol<Serializable> {

    private T arg;

    public RemoteCommandInvocationProtocol(T arg) {
        this.arg = arg;
    }

    @Override
    public void start(int connectionId, Connections<Serializable> connections) {

    }

    @Override
    public Serializable process(Serializable msg,int idOfSender) {
        return ((Command) msg).execute(arg);
    }

    @Override
    public boolean shouldTerminate() {
        return false;
    }

}
