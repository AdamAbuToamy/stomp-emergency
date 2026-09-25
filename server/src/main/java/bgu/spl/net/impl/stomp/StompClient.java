package bgu.spl.net.impl.stomp;

import java.io.*;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

public class StompClient {
    private static final String HOST = "localhost";
    private static final int PORT = 7777;

    public static void main(String[] args) {
        boolean shouldStomp = false;
        StompEndec endec = new StompEndec();
        try (Socket socket = new Socket(HOST, PORT);
             BufferedReader keyboard = new BufferedReader(new InputStreamReader(System.in));
             BufferedInputStream in = new BufferedInputStream(socket.getInputStream());
             BufferedOutputStream out = new BufferedOutputStream(socket.getOutputStream());) {

            // Create a thread to handle server responses
            Thread serverListener = new Thread(() -> {
                try {
                    int read;
                    String response;

                    while ((read = in.read()) >= 0) {
                        response = endec.decodeNextByte((byte) read);
                        if(response != null && !response.equals("")) {
                            System.out.println("Server response: " + response);
                        }
                    }
                } catch (Exception e) {
                    e.printStackTrace();
                }
            });
            serverListener.start();

            // Send CONNECT frame
            String connectFrame = "CONNECT\n" +
                    "accept-version:1.2\n" +
                    "host:stomp.cs.bgu.ac.il\n" +
                    "login:userJava\n" +
                    "passcode:password\n" +
                    "receipt:1\n" +
                    "\n" +
                    "\u0000";

            out.write(endec.encode(connectFrame));
            out.flush();

            // Handle user input in main thread
            String userInput;
            while ( (!shouldStomp) && ((userInput = keyboard.readLine()) != null) ) {
                if (userInput.equalsIgnoreCase("quit")) {
                    String disconnectFrame = "DISCONNECT\n" +
                            "receipt:10\n" +
                            "\n" +
                            "\u0000";
                    out.write(endec.encode(disconnectFrame));
                    out.flush();
                }

                if (userInput.startsWith("sub")) {
                    String subscribeFrame = "SUBSCRIBE\n" +
                            "receipt:2\n" +
                            "destination:/hi\n" +
                            "id:1\n" +
                            "\n" +
                            "\u0000";
                    out.write(endec.encode(subscribeFrame));
                    out.flush();
                }

                if (userInput.startsWith("send")) {
                    String subscribeFrame =  "SEND\n" +
                            "destination:/hi\n" +
                            "receipt:3\n" +
                            "\n" +
                            "we sent a good message!!\n" +
                            "\u0000";
                    out.write(endec.encode(subscribeFrame));
                    out.flush();
                }

                if (userInput.startsWith("unsub")) {
                    String subscribeFrame =  "UNSUBSCRIBE\n" +
                            "receipt:4\n" +
                            "id:1\n" +
                            "\n" +
                            "\u0000";
                    out.write(endec.encode(subscribeFrame));
                    out.flush();
                }
            }

        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}
