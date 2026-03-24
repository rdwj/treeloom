// Simple C++ class fixture: class with constructor, methods, and member variables.
#include <string>

class Animal {
public:
    Animal(std::string name, int age) : name_(name), age_(age) {}

    std::string getName() const {
        return name_;
    }

    int getAge() const {
        return age_;
    }

    void setAge(int age) {
        age_ = age;
    }

protected:
    std::string name_;
    int age_;
};

class Dog : public Animal {
public:
    Dog(std::string name, int age) : Animal(name, age) {}

    std::string speak() {
        std::string greeting = "Woof from ";
        return greeting;
    }
};
