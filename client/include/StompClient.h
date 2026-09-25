#pragma once
#include "ConnectionHandler.h"
#include "StompProtocol.h"
#include "event.h"
#include <string>
#include <thread>
#include <mutex>
#include <map>
#include <vector>
#include <atomic>

class StompClient {
private:
    std::atomic<bool> ServerConnected;
    std::atomic<bool> connected;
    std::atomic<bool> shouldTerminate;
    int nextSubscriptionId;
    int nextReceiptId;
    StompProtocol& protocol;
    std::string currentUser;
    std::mutex eventsMutex;
    
    // Map of channel -> user -> vector of events
    std::map<std::string, std::map<std::string, std::vector<Event>>> channelEvents;
    std::map<int, std::string> receipts;
    std::map<std::string, int> subscriptionIds;

    void handleFrame(const std::string& frame);
    void processCommand(const std::string& command);
    
    // Command handlers
    void handleLogin(const std::vector<std::string>& tokens);
    void handleJoin(const std::vector<std::string>& tokens);
    void handleExit(const std::vector<std::string>& tokens);
    void handleReport(const std::vector<std::string>& tokens);
    void handleSummary(const std::vector<std::string>& tokens);
    void handleLogout();
    
    // Helper methods
    std::vector<std::string> splitCommand(const std::string& command);
    std::string epochToDateTime(int epochTime);
    void addEvent(const std::string& channel, const std::string& user, const Event& event);

public:
    StompClient(StompProtocol& protocol);
    ~StompClient();
    void readFromSocket();
    void readFromKeyboard();
}; 