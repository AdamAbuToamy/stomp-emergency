package io.github.adamabutoamy.stomp.protocol;

import com.sun.net.httpserver.HttpServer;
import io.github.adamabutoamy.stomp.server.ConnectionsImpl;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class ServerMonitor implements AutoCloseable {
    private final HttpServer http;
    private final ExecutorService executor;

    private ServerMonitor(int port, String mode) throws Exception {
        long started = System.nanoTime();
        http = HttpServer.create(
                new InetSocketAddress("127.0.0.1", 7778), 0);
        executor = Executors.newSingleThreadExecutor(r -> {
            Thread thread = new Thread(r, "stomp-monitor");
            thread.setDaemon(true);
            return thread;
        });
        http.setExecutor(executor);
        http.createContext("/status", exchange -> {
            try {
                if (!"GET".equals(exchange.getRequestMethod())
                        || !"/status".equals(exchange.getRequestURI().getPath())) {
                    exchange.sendResponseHeaders(404, -1);
                    return;
                }

                ConnectionsImpl<?> connections = ConnectionsImpl.getInstance();
                long uptime = (System.nanoTime() - started) / 1_000_000_000L;
                String json = "{"
                        + "\"mode\":\"" + mode + "\","
                        + "\"port\":" + port + ","
                        + "\"connections\":" + connections.activeConnectionCount() + ","
                        + "\"users\":" + StompMessagingProtocol.authenticatedUserCount() + ","
                        + "\"channels\":" + connections.activeChannelCount() + ","
                        + "\"uptime_seconds\":" + uptime
                        + "}";

                byte[] body = json.getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set(
                        "Content-Type", "application/json; charset=utf-8");
                exchange.getResponseHeaders().set("Cache-Control", "no-store");
                exchange.sendResponseHeaders(200, body.length);
                exchange.getResponseBody().write(body);
            } finally {
                exchange.close();
            }
        });
        http.start();
    }

    public static ServerMonitor start(int port, String mode) {
        try {
            return new ServerMonitor(port, mode);
        } catch (Exception error) {
            ServerLog.event("WARN", "MONITOR_UNAVAILABLE", -1,
                    "Could not start local monitor on port 7778");
            return null;
        }
    }

    @Override
    public void close() {
        http.stop(0);
        executor.shutdownNow();
    }
}
