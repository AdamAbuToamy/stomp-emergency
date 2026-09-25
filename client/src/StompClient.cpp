#include "StompClient.h"
#include <iostream>
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
	channelEvents(),
	receipts(),
	subscriptionIds(){}


void StompClient::readFromSocket() {
	while (!shouldTerminate) {
		if(ServerConnected){
			try {
				StompFrame frame = protocol.receiveFrame();
				handleFrame(frame.toString());
			
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
		std::getline(std::cin, command);
		if (!command.empty()) {
			processCommand(command);
		}
	}
}

void StompClient::handleFrame(const std::string& frame) {

	std::istringstream iss(frame);
	std::string frameType;
	iss >> frameType;

	if (frameType == "CONNECTED") {
		std::cout << "Login successful" << std::endl;
		connected = true;
		protocol.setConnected(true);
	}
	else if (frameType == "RECEIPT") {
		std::string line;
		std::string receiptId;
		while (std::getline(iss, line)) {
			if (line.find("receipt-id:") != std::string::npos) {
				receiptId = line.substr(11);
			}
		}
		
		int receipt = std::stoi(receiptId);
		if (receipt == -1) {
			connected = false;
			ServerConnected = false;
			protocol.setConnected(false);
			protocol.closeHandler();
		} else {
			std::cout << receipts[receipt] << std::endl;
		}
	}
	else if (frameType == "MESSAGE") {
		
		std::string body;
		bool bodyStart = false;
		std::string line;
		while (std::getline(iss, line)) {
			if (line.empty() && !bodyStart) {
				bodyStart = true;
				continue;
			}       

			if (bodyStart) {
				body += line + "\n";
			}
		}
		
		Event event(body);
		std::lock_guard<std::mutex> lock(eventsMutex);
		addEvent(event.get_channel_name(), event.getEventOwnerUser(), event);
	}
	else if (frameType == "ERROR") {
		std::string line;
		std::string body;
		bool bodyStart = false;

		while (std::getline(iss, line)) {
			if (line.empty() && !bodyStart) {
				bodyStart = true;
				continue;
			}
			if (bodyStart) {
				body += line + "\n";
			}
		}

		connected = false;
		ServerConnected = false;
		protocol.setConnected(false);
		protocol.closeHandler();
		
	}
}

void StompClient::handleLogin(const std::vector<std::string>& tokens) {

	std::string hostPort = tokens[1];
	int colonPos = hostPort.find(':');
	std::string host = hostPort.substr(0, colonPos);
	std::string port = hostPort.substr(colonPos + 1);

	currentUser = tokens[2];
	std::string password = tokens[3];

	if(protocol.connect(host, currentUser, password)){
		ServerConnected = true;
	}
}

void StompClient::handleJoin(const std::vector<std::string>& tokens) {
	
	std::string channel = tokens[1];
	if(subscriptionIds.find(channel) == subscriptionIds.end()){
		int subscriptionId = nextSubscriptionId++;
		int receiptId = nextReceiptId++;
		subscriptionIds[channel] = subscriptionId;

		if (protocol.subscribe(channel, std::to_string(subscriptionId), std::to_string(receiptId))) {
		receipts[receiptId] = "Joined channel " + channel;
		}
	}
	else{
		std::cout << "User already logged in to " << channel << std::endl;
	}
}

void StompClient::handleExit(const std::vector<std::string>& tokens) {
	
	std::string channel = tokens[1];
	int receiptId = nextReceiptId++;
	
	if (protocol.unsubscribe(std::to_string(subscriptionIds[channel]), std::to_string(receiptId))){
		receipts[receiptId] = "Exited channel " + channel;
		std::map<std::string, int>::iterator it = subscriptionIds.find(channel);
		subscriptionIds.erase(it);
	}
}

void StompClient::handleReport(const std::vector<std::string>& tokens) {

	std::string filename = tokens[1];
	names_and_events eventsData = parseEventsFile(filename);
	
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
	

	auto& events = channelEvents[channel][user];
	
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
	std::vector<std::string> tokens = splitCommand(command);
	if (tokens.empty()) return;

	std::string cmd = tokens[0];
	if (cmd == "login") {
		handleLogin(tokens);
	}
	else if (cmd == "join" && connected) {
		handleJoin(tokens);
	}
	else if (cmd == "exit" && connected) {
		handleExit(tokens);
	}
	else if (cmd == "report" && connected) {
		handleReport(tokens);
	}
	else if (cmd == "summary" && connected) {
		handleSummary(tokens);
	}
	else if (cmd == "logout" && connected) {
		handleLogout();
	}
}

StompClient::~StompClient(){
	for(auto &item : channelEvents){
		for(auto &it: item.second){
			it.second.clear();
			item.second.erase(it.first);
		}
		item.second.~map();
	}
	eventsMutex.~mutex();
	for(auto &item : channelEvents){
		channelEvents.erase(item.first);
	}
	for(auto &item : receipts){
		receipts.erase(item.first);
	}
	for(auto &item : subscriptionIds){
		subscriptionIds.erase(item.first);
	}
	channelEvents.~map();
	receipts.~map();
	subscriptionIds.~map();
}

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