package io.github.adamabutoamy.stomp.protocol;
import io.github.adamabutoamy.stomp.server.Server;

public class StompServer {

    public static void main(String[] args) {
        // TODO: implement this
        if (args.length != 2) {
            args = new String[]{"7777", "tpc"};
        }
        int port = Integer.parseInt(args[0]);
        String serverType = args[1].toLowerCase();

        if (serverType.equals("tpc")) {
            Server<String> server = Server.threadPerClient(
                    port,
                    StompMessagingProtocol::new,
                    StompEndec::new
            );
            ServerMonitor monitor = ServerMonitor.start(port, serverType);
            try {
                server.serve();
            } finally {
                if (monitor != null) monitor.close();
            }
        }
        else if (serverType.equals("reactor")) {
            Server<String> server = Server.reactor(
                    Runtime.getRuntime().availableProcessors(),
                    port,
                    StompMessagingProtocol::new,
                    StompEndec::new
            );
            ServerMonitor monitor = ServerMonitor.start(port, serverType);
            try {
                server.serve();
            } finally {
                if (monitor != null) monitor.close();
            }
        }
        else {
            System.out.println("Invalid server type. Use 'reactor' or 'tpc'");
            System.exit(1);
        }
    }
}
