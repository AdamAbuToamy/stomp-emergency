package bgu.spl.net.impl.stomp;
import bgu.spl.net.srv.Server;

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
            server.serve();
        }
        else if (serverType.equals("reactor")) {
            Server<String> server = Server.reactor(
                    Runtime.getRuntime().availableProcessors(),
                    port,
                    StompMessagingProtocol::new,
                    StompEndec::new
            );
            server.serve();
        }
        else {
            System.out.println("Invalid server type. Use 'reactor' or 'tpc'");
            System.exit(1);
        }
    }
}
