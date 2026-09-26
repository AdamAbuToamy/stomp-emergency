#include "event.h"
#include <iostream>
#include <stdexcept>
#include <string>

static std::string report(const std::string& city) {
    return "user:demo_user\n"
           "city:" + city + "\n"
           "event name:Training report\n"
           "date time:1700000000\n"
           "general information:\n"
           " active:true\n"
           " forces_arrival_at_scene:false\n"
           "description:\n"
           "Road closed: use another route.\n";
}

static void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

static void ordinary_fields_are_read() {
    Event event(report("Test City"));
    require(event.get_city() == "Test City", "ordinary city was not preserved");
    require(event.getEventOwnerUser() == "demo_user", "wrong event owner");
    require(event.get_name() == "Training report", "wrong event name");
    require(event.get_date_time() == 1700000000, "wrong event timestamp");
}

static void colon_inside_city_is_preserved() {
    Event event(report("Test City:North"));
    require(event.get_city() == "Test City:North",
            "expected city [Test City:North], received [" + event.get_city() + "]");
}

static void description_is_not_general_information() {
    Event event(report("Test City"));
    const auto& info = event.get_general_information();
    require(info.count("active") == 1 && info.at("active") == "true",
            "active field is missing or incorrect");
    require(info.count("forces_arrival_at_scene") == 1
            && info.at("forces_arrival_at_scene") == "false",
            "forces_arrival_at_scene field is missing or incorrect");
    std::string keys;
    for (const auto& entry : info) keys += "[" + entry.first + "] ";
    require(info.size() == 2, "expected exactly two general fields; got " + keys);
    require(event.get_description() == "Road closed: use another route.\n",
            "description was not preserved");
}

int main() {
    struct Test { const char* name; void (*run)(); };
    const Test tests[] = {
        {"ordinary_fields_are_read", ordinary_fields_are_read},
        {"colon_inside_city_is_preserved", colon_inside_city_is_preserved},
        {"description_is_not_general_information", description_is_not_general_information}
    };
    int failures = 0;
    for (const auto& test : tests) {
        try {
            test.run();
            std::cout << "PASS " << test.name << '\n';
        } catch (const std::exception& error) {
            ++failures;
            std::cout << "FAIL " << test.name << ": " << error.what() << '\n';
        }
    }
    std::cout << "Ran 3 tests; failures: " << failures << '\n';
    return failures == 0 ? 0 : 1;
}
