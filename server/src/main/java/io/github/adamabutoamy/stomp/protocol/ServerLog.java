package io.github.adamabutoamy.stomp.protocol;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.logging.*;

public final class ServerLog {
    private static final Logger LOG = Logger.getLogger("stomp.events");

    static {
        LOG.setUseParentHandlers(false);
        LOG.setLevel(Level.ALL);

        Formatter formatter = new Formatter() {
            @Override
            public String format(LogRecord record) {
                return Instant.ofEpochMilli(record.getMillis())
                        + " " + record.getLevel().getName()
                        + " " + record.getMessage()
                        + System.lineSeparator();
            }
        };

        ConsoleHandler console = new ConsoleHandler();
        console.setLevel(Level.ALL);
        console.setFormatter(formatter);
        LOG.addHandler(console);

        try {
            Files.createDirectories(Path.of("logs"));
            FileHandler file = new FileHandler(
                    "logs/stomp-server-%g.log", 1000000, 3, true);
            file.setEncoding("UTF-8");
            file.setLevel(Level.ALL);
            file.setFormatter(formatter);
            LOG.addHandler(file);
        } catch (Exception error) {
            LOG.warning("FILE_LOG_UNAVAILABLE: " + clean(error.getMessage()));
        }
    }

    private ServerLog() {}

    private static String clean(String value) {
        if (value == null) return "";
        String text = value.replaceAll("\\p{Cntrl}", " ");
        return text.length() > 300 ? text.substring(0, 300) : text;
    }

    public static void event(
            String level, String event, int connectionId, String detail) {
        Level severity = "WARN".equals(level) ? Level.WARNING : Level.INFO;
        LOG.log(severity, clean(event)
                + " connection=" + connectionId
                + " detail=" + clean(detail));
    }
}
