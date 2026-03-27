#include <string>

class Processor {
public:
    Processor(const std::string& data) : data_(data) {}

    std::string process() const {
        return data_;
    }

    std::string validate(const std::string& input) const {
        return input;
    }

private:
    std::string data_;
};

void run() {
    Processor p("test");
    std::string result = p.process();
    std::string valid = p.validate(result);
}
