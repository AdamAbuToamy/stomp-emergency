CFLAGS:=-c -Wall -Weffc++ -g -std=c++11 -Iinclude -pthread
LDFLAGS:=-pthread

all: StompEMIClient

StompEMIClient: bin/ConnectionHandler.o bin/StompClient.o bin/event.o bin/StompProtocol.o
	g++ -o bin/StompEMIClient bin/ConnectionHandler.o bin/StompClient.o bin/event.o bin/StompProtocol.o $(LDFLAGS)

bin/ConnectionHandler.o: src/ConnectionHandler.cpp
	g++ $(CFLAGS) -o bin/ConnectionHandler.o src/ConnectionHandler.cpp

bin/event.o: src/event.cpp
	g++ $(CFLAGS) -o bin/event.o src/event.cpp

bin/StompClient.o: src/StompClient.cpp
	g++ $(CFLAGS) -o bin/StompClient.o src/StompClient.cpp

bin/StompProtocol.o: src/StompProtocol.cpp
	g++ $(CFLAGS) -o bin/StompProtocol.o src/StompProtocol.cpp

clean:
	rm -f bin/*

# Add .PHONY target for clean and all
.PHONY: clean all

# Rebuild objects when project headers change.
HEADERS := $(wildcard include/*.h) $(wildcard include/*.hpp)
OBJECTS := bin/ConnectionHandler.o bin/StompClient.o bin/event.o bin/StompProtocol.o

$(OBJECTS): $(HEADERS) | bin

bin:
	mkdir -p bin
