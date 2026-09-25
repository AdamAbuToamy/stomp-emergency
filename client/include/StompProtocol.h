#pragma once

#include "../include/ConnectionHandler.h"
#include <string>
#include <map>
#include <vector>

// Represents a STOMP frame with its components
class StompFrame {
private:
    std::string command;
    std::map<std::string, std::string> headers;
    std::string body;

public:
    StompFrame(const std::string& cmd);
    
    // Add header to the frame
    void addHeader(const std::string& name, const std::string& value);
    
    // Set the frame body
    void setBody(const std::string& frameBody);
    
    // Convert frame to string format for sending
    std::string toString() const;
    ~StompFrame();
    // Getters
    std::string getCommand() const;
    std::string getHeader(const std::string& name) const;
    std::string getBody() const;
};

class StompProtocol {
private:
    ConnectionHandler& connectionHandler;
    bool connected;
    bool ServerConnected;
    
    // Helper methods
    StompFrame parseFrame(const std::string& rawFrame);
    std::vector<std::string> splitLines(const std::string& str);

public:
    StompProtocol(ConnectionHandler& handler);
    
    // Connect to STOMP server
    bool connect(const std::string& host, const std::string& login, const std::string& passcode);
    
    // Send a STOMP frame
    bool sendFrame(const StompFrame& frame);
    
    // Receive a STOMP frame
    StompFrame receiveFrame();
    
    // Check if connected
    bool isConnected() const;
    void setConnected(bool val);
    
    // Disconnect from server
    bool disconnect();
    
    bool subscribe(const std::string& destination, const std::string& subId, const std::string& receiptId);
    bool unsubscribe(const std::string& subId, const std::string& receiptId);
    bool send(const std::string& destination, const std::string& eventDetails);
    void closeHandler();
};
