// C++ functions fixture: standalone functions and a template function.
#include <string>

int add(int a, int b) {
    int result = a + b;
    return result;
}

int multiply(int x, int y) {
    return x * y;
}

template<typename T>
T max_val(T a, T b) {
    return a > b ? a : b;
}

std::string greet(std::string name) {
    std::string msg = "Hello, ";
    return msg;
}

int main() {
    int sum = add(3, 4);
    int product = multiply(sum, 2);
    std::string greeting = greet("World");
    return 0;
}
