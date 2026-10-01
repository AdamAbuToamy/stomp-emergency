#include "StompClient.h"
#include <iostream>
#include <exception>
#include <fstream>
#include <sstream>
#include <algorithm>
#include <ctime>
#include <iomanip>
#include "StompProtocol.h"

StompClient::StompClient(StompProtocol& protocol) : 
	ServerConnected(false),
	connected(false), 
	shouldTerminate(false), 
	nextSubscriptionId(0),
	nextReceiptId(0),
	protocol(protocol),
	currentUser(""),
	eventsMutex(),
	receiptsMutex(),
	channelEvents(),
	receipts(),
	subscriptionIds(){}


void StompClient::readFromSocket() {
	while (!shouldTerminate) {
		if(ServerConnected){
			try {
				StompFrame frame = protocol.receiveFrame();
				handleFrame(frame);
			
			} 
			catch (const std::runtime_error& e){}
			catch (const int e){
				connected = false;
				ServerConnected = false;
				protocol.setConnected(false);
				protocol.closeHandler();
			}
		}
	}
}

void StompClient::readFromKeyboard() {
	while (!shouldTerminate) {
		std::string command;
		if (!std::getline(std::cin, command)) {
            shouldTerminate = true;
            protocol.requestShutdown();
            break;
        }
		if (!command.empty()) {
			processCommand(command);
		}
	}
}

void StompClient::handleFrame(const StompFrame& frame) {
    const std::string frameType = frame.getCommand();

    if (frameType == "CONNECTED") {
        connected = true;
        protocol.setConnected(true);
        std::cout << "Login successful" << std::endl;
    } else if (frameType == "RECEIPT") {
        const std::string receiptId = frame.getHeader("receipt-id");
        const int receipt = std::stoi(receiptId);
        if (receipt == -1) {
            connected = false;
            ServerConnected = false;
            protocol.setConnected(false);
            protocol.closeHandler();
        } else {
            std::string confirmation;
            {
                std::lock_guard<std::mutex> lock(receiptsMutex);
                auto it = receipts.find(receipt);
                if (it != receipts.end()) {
                    confirmation = it->second;
                    receipts.erase(it);
                }
            }
            if (!confirmation.empty()) {
                std::cout << confirmation << std::endl;
            }
        }
    } else if (frameType == "MESSAGE") {
        const std::string channel = frame.getHeader("destination");
        if (channel.empty()) {
            std::cerr << "Message error: missing destination" << std::endl;
            return;
        }
        Event event(frame.getBody());
        std::lock_guard<std::mutex> lock(eventsMutex);
        addEvent(channel, event.getEventOwnerUser(), event);
    } else if (frameType == "ERROR") {
        std::cerr << "Server error: " << frame.getHeader("message") << std::endl;
        if (!frame.getBody().empty()) {
            std::cerr << frame.getBody() << std::endl;
        }
        connected = false;
        ServerConnected = false;
        protocol.setConnected(false);
        protocol.closeHandler();
    }
}

void StompClient::handleLogin(const std::vector<std::string>& tokens) {
    if (ServerConnected) {
        std::cout << "Already connected or waiting for login. Log out first."
                  << std::endl;
        return;
    }

    const std::string& endpoint = tokens[1];
    const std::size_t colon = endpoint.find(':');

    if (colon == std::string::npos || colon == 0
            || colon + 1 == endpoint.size()
            || endpoint.find(':', colon + 1) != std::string::npos) {
        std::cout << "Login error: expected IPv4:port." << std::endl;
        return;
    }

    const std::string host = endpoint.substr(0, colon);
    const std::string portText = endpoint.substr(colon + 1);
    unsigned int port = 0;

    for (char digit : portText) {
        if (digit < '0' || digit > '9') {
            std::cout << "Login error: port must be a number from 1 to 65535."
                      << std::endl;
            return;
        }
        port = port * 10 + static_cast<unsigned int>(digit - '0');
        if (port > 65535) {
            std::cout << "Login error: port must be from 1 to 65535."
                      << std::endl;
            return;
        }
    }

    if (port == 0) {
        std::cout << "Login error: port must be from 1 to 65535." << std::endl;
        return;
    }

    if (protocol.connect(host, static_cast<unsigned short>(port),
                         tokens[2], tokens[3])) {
        currentUser = tokens[2];
        ServerConnected = true;
    }
}

void StompClient::handleJoin(const std::vector<std::string>& tokens) {
    const std::string& channel = tokens[1];
    if (subscriptionIds.find(channel) != subscriptionIds.end()) {
        std::cout << "Already subscribed to " << channel << std::endl;
        return;
    }

    const int subscriptionId = nextSubscriptionId++;
    const int receiptId = nextReceiptId++;
    {
        std::lock_guard<std::mutex> lock(receiptsMutex);
        receipts[receiptId] = "Joined channel " + channel;
    }

    if (protocol.subscribe(channel, std::to_string(subscriptionId),
                           std::to_string(receiptId))) {
        subscriptionIds[channel] = subscriptionId;
    } else {
        {
            std::lock_guard<std::mutex> lock(receiptsMutex);
            receipts.erase(receiptId);
        }
        std::cerr << "Could not send subscription request." << std::endl;
    }
}

void StompClient::handleExit(const std::vector<std::string>& tokens) {
    const std::string& channel = tokens[1];
    auto subscription = subscriptionIds.find(channel);
    if (subscription == subscriptionIds.end()) {
        std::cout << "Not subscribed to " << channel << std::endl;
        return;
    }

    const int receiptId = nextReceiptId++;
    {
        std::lock_guard<std::mutex> lock(receiptsMutex);
        receipts[receiptId] = "Exited channel " + channel;
    }

    if (protocol.unsubscribe(std::to_string(subscription->second),
                             std::to_string(receiptId))) {
        subscriptionIds.erase(subscription);
    } else {
        {
            std::lock_guard<std::mutex> lock(receiptsMutex);
            receipts.erase(receiptId);
        }
        std::cerr << "Could not send unsubscribe request." << std::endl;
    }
}

void StompClient::handleReport(const std::vector<std::string>& tokens) {

	std::string filename = tokens[1];
	names_and_events eventsData;
    try {
        eventsData = parseEventsFile(filename);
    } catch (const std::exception& error) {
        std::cerr << "Report error: " << error.what() << std::endl;
        return;
    }
	
	for (const Event& event : eventsData.events) {
		

		std::string msg;
		msg = "user:" + currentUser + "\n";
		msg += "city:" + event.get_city() + "\n";
		msg += "event name:" + event.get_name() + "\n";
		msg += "date time:" + std::to_string(event.get_date_time()) + "\n";
		msg += "general information:\n";
		for( auto &item : event.get_general_information()){
			msg += "	" + item.first + ":" + item.second + "\n";
		}
		msg += "description:\n" + event.get_description();

		protocol.send(eventsData.channel_name, msg);
	}
}

std::string StompClient::epochToDateTime(int epochTime) {
	time_t time = epochTime;
	struct tm* timeinfo = localtime(&time);
	std::stringstream ss;
	ss << std::put_time(timeinfo, "%d/%m/%y %H:%M");
	return ss.str();
}

void StompClient::handleSummary(const std::vector<std::string>& tokens) {
	
	std::string channel = tokens[1];
	std::string user = tokens[2];
	std::string filename = tokens[3];
	

	std::vector<Event> events;
    {
        std::lock_guard<std::mutex> lock(eventsMutex);
        const auto channelIt = channelEvents.find(channel);
        if (channelIt != channelEvents.end()) {
            const auto userIt = channelIt->second.find(user);
            if (userIt != channelIt->second.end()) {
                events = userIt->second;
            }
        }
    }
	
	// Calculate stats
	int totalReports = events.size();
	int activeCount = 0;
	int forcesArrivalCount = 0;

	for (const auto& event : events) {
		const auto& info = event.get_general_information();
		if (info.find("active") != info.end() && info.at("active") == "true")
			activeCount++;
		if (info.find("forces_arrival_at_scene") != info.end() && 
			info.at("forces_arrival_at_scene") == "true")
			forcesArrivalCount++;
	}

	// Open file in truncation mode to clear any existing content
	std::ofstream outFile(filename, std::ios::trunc);
	if (!outFile.is_open()) {
		std::cout << "Error: Could not open file " << filename << std::endl;
		return;
	}

	// Write summary to file
	outFile << "Channel " << channel << std::endl;
	outFile << "Stats:" << std::endl;
	outFile << "Total: " << totalReports << std::endl;
	outFile << "active: " << activeCount << std::endl;
	outFile << "forces arrival at scene: " << forcesArrivalCount << std::endl;
	outFile << "Event Reports:" << std::endl;

	for (size_t i = 0; i < events.size(); i++) {
		const auto& event = events[i];
		outFile << "Report_" << (i + 1) << ":" << std::endl;
		outFile << "city: " << event.get_city() << std::endl;
		outFile << "date time: " << epochToDateTime(event.get_date_time()) << std::endl;
		outFile << "event name: " << event.get_name() << std::endl;
		
		std::string description = event.get_description();
		if (description.length() > 27) {
			description = description.substr(0, 27) + "...";
		}
		outFile << "summary: " << description << std::endl;
	}

	outFile.close();
}

void StompClient::handleLogout() {
	protocol.disconnect();
}

void StompClient::addEvent(const std::string& channel, const std::string& user, const Event& event) {
	auto& events = channelEvents[channel][user];
	
	// Find the correct position to insert the new event (ordered by time)
	auto insertPos = std::lower_bound(events.begin(), events.end(), event,
		[](const Event& a, const Event& b) {
			return a.get_date_time() < b.get_date_time();
		});
	
	events.insert(insertPos, event);
}

std::vector<std::string> StompClient::splitCommand(const std::string& command) {
	std::vector<std::string> tokens;
	std::istringstream iss(command);
	std::string token;
	while (iss >> token) {
		tokens.push_back(token);
	}
	return tokens;
}

void StompClient::processCommand(const std::string& command) {
    const std::vector<std::string> tokens = splitCommand(command);
    if (tokens.empty()) return;

    const std::string& cmd = tokens[0];
    std::size_t expectedWords = 0;
    const char* usage = nullptr;

    if (cmd == "login") {
        expectedWords = 4;
        usage = "Usage: login <host:port> <username> <password>";
    } else if (cmd == "join") {
        expectedWords = 2;
        usage = "Usage: join <channel>";
    } else if (cmd == "exit") {
        expectedWords = 2;
        usage = "Usage: exit <channel>";
    } else if (cmd == "report") {
        expectedWords = 2;
        usage = "Usage: report <file>";
    } else if (cmd == "summary") {
        expectedWords = 4;
        usage = "Usage: summary <channel> <user> <output-file>";
    } else if (cmd == "logout") {
        expectedWords = 1;
        usage = "Usage: logout";
    } else {
        std::cout << "Unknown command: " << cmd << std::endl;
        return;
    }

    if (tokens.size() != expectedWords) {
        std::cout << usage << std::endl;
        return;
    }

    if (cmd == "login") {
        handleLogin(tokens);
        return;
    }
    if (!connected) {
        std::cout << "Please log in first." << std::endl;
        return;
    }

    if (cmd == "join") handleJoin(tokens);
    else if (cmd == "exit") handleExit(tokens);
    else if (cmd == "report") handleReport(tokens);
    else if (cmd == "summary") handleSummary(tokens);
    else if (cmd == "logout") handleLogout();
}

StompClient::~StompClient() = default;

int main(int argc, char *argv[]) {
	std::string host = "127.0.0.1";
	short port = 7777;
	
	ConnectionHandler connectionHandler(host, port);
	StompProtocol protocol(connectionHandler);
	StompClient client(protocol);
	
	std::thread keyboardThread(&StompClient::readFromKeyboard, &client);
	std::thread socketThread(&StompClient::readFromSocket, &client);
	
	if (keyboardThread.joinable()) keyboardThread.join();
	if (socketThread.joinable()) socketThread.join();
	
	return 0;
}