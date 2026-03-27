#include <iostream>
#include <string>

std::string source() {
    return "tainted";
}

std::string passthrough(const std::string& data) {
    return data;
}

void sink(const std::string& value) {
    std::cout << value << std::endl;
}

int main() {
    std::string data = source();
    std::string processed = passthrough(data);
    sink(processed);
    return 0;
}
