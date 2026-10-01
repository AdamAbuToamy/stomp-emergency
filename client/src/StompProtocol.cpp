#include "../include/StompProtocol.h"
#include <sstream>
#include <stdexcept>

// StompFrame Implementation
StompFrame::StompFrame(const std::string& cmd) : command(cmd), headers(), body() {}

void StompFrame::addHeader(const std::string& name, const std::string& value) {
    headers[name] = value;
}

void StompFrame::setBody(const std::string& frameBody) {
    body = frameBody;
}

std::string StompFrame::toString() const {
    std::stringstream frame;
    
    // Add command
    frame << command << "\n";
    
    // Add headers
    for (const auto& header : headers) {
        frame << header.first << ":" << header.second << "\n";
    }
    
    // Add blank line before body
    frame << "\n";
    
    // Add body if exists
    if (!body.empty()) {
        frame << body;
    }
    
    // Add frame terminator
    frame << "\0";
    
    return frame.str();
}

std::string StompFrame::getCommand() const {
    return command;
}

std::string StompFrame::getHeader(const std::string& name) const {
    auto it = headers.find(name);
    if (it != headers.end()) {
        return it->second;
    }
    return "";
}

std::string StompFrame::getBody() const {
    return body;
}

StompFrame::~StompFrame() = default;

// StompProtocol Implementation
StompProtocol::StompProtocol(ConnectionHandler& handler) 
    : connectionHandler(handler), connected(false), ServerConnected(false) {}

bool StompProtocol::connect(const std::string& host, unsigned short port, const std::string& login, const std::string& passcode) {
    if (connected) {
        std::cout << "The client is already logged in, log out before trying again" << std::endl;
        return false;
    }

    StompFrame connectFrame("CONNECT");
    connectFrame.addHeader("accept-version", "1.2");
    connectFrame.addHeader("host", "stomp.cs.bgu.ac.il");
    connectFrame.addHeader("login", login);
    connectFrame.addHeader("passcode", passcode);

    if(!ServerConnected){
        if(!connectionHandler.connect(host, port)){
            std::cout << "Could not connect to the server" << std::endl;
            return false;
        }
    }

    if (!sendFrame(connectFrame)) {
        closeHandler();
        std::cout << "Could not connect to the server" << std::endl;
        return false;
    }
       
    ServerConnected = true;
    return true;
}

bool StompProtocol::sendFrame(const StompFrame& frame) {
    std::string frameStr = frame.toString();
    return connectionHandler.sendFrameAscii(frameStr, '\0');
}

StompFrame StompProtocol::receiveFrame() {
    std::string rawFrame;
    if (!connectionHandler.getFrameAscii(rawFrame, '\0')) {
        //throw std::runtime_error("Failed to receive frame");
        throw 1;
    }
    return parseFrame(rawFrame);
}

StompFrame StompProtocol::parseFrame(const std::string& rawFrame) {
    std::vector<std::string> lines = splitLines(rawFrame);
    if (lines.empty()) {
        throw std::runtime_error("Empty frame received");
    }

    // First line is the command
    StompFrame frame(lines[0]);
    
    // Parse headers
    size_t i = 1;
    while (i < lines.size() && !lines[i].empty()) {
        std::string line = lines[i];
        size_t colonPos = line.find(':');
        if (colonPos != std::string::npos) {
            std::string headerName = line.substr(0, colonPos);
            std::string headerValue = line.substr(colonPos + 1);
            frame.addHeader(headerName, headerValue);
        }
        i++;
    }

    // Skip the empty line after headers
    i++;

    // Remaining lines form the body
    std::stringstream bodyStream;
    while (i < lines.size()) {
        bodyStream << lines[i];
        if (i < lines.size() - 1) {
            bodyStream << "\n";
        }
        i++;
    }
    frame.setBody(bodyStream.str());

    return frame;
}

std::vector<std::string> StompProtocol::splitLines(const std::string& str) {
    std::vector<std::string> lines;
    std::stringstream ss(str);
    std::string line;

    while (std::getline(ss, line, '\n')) {
        // Remove \r if present (handles Windows-style line endings)
        if (!line.empty() && line[line.length()-1] == '\r') {
            line = line.substr(0, line.length()-1);
        }
        lines.push_back(line);
    }

    return lines;
}

bool StompProtocol::isConnected() const {
    return connected;
}

void StompProtocol::setConnected(bool val){
    connected = val;
}

bool StompProtocol::disconnect() {
    if (!connected) {
        return false;
    }
    
    StompFrame disconnectFrame("DISCONNECT");
    disconnectFrame.addHeader("receipt", "-1");
    if (!sendFrame(disconnectFrame)) {
        return false;
    }
 

    return true;
}

bool StompProtocol::subscribe(const std::string& destination, const std::string& subId, const std::string& receiptId) {
    if (!connected) {
        return false;
    }

    StompFrame subscribeFrame("SUBSCRIBE");
    subscribeFrame.addHeader("destination", destination);
    subscribeFrame.addHeader("id", subId);
    subscribeFrame.addHeader("receipt", receiptId);

    return sendFrame(subscribeFrame);
}

bool StompProtocol::unsubscribe(const std::string& subId, const std::string& receiptId) {
    if (!connected) {
        return false;
    }

    StompFrame unsubscribeFrame("UNSUBSCRIBE");
    unsubscribeFrame.addHeader("id", subId);
    unsubscribeFrame.addHeader("receipt", receiptId);

    return sendFrame(unsubscribeFrame);
}

bool StompProtocol::send(const std::string& destination, const std::string& eventDetails) {
    if (!connected) {
        return false;
    }

    StompFrame messageFrame("SEND");
    messageFrame.addHeader("destination", destination);

    messageFrame.setBody(eventDetails);

    return sendFrame(messageFrame);
} 

void StompProtocol::closeHandler(){
    connectionHandler.close();
    ServerConnected = false;
}
void StompProtocol::requestShutdown() {
    connectionHandler.requestShutdown();
}
