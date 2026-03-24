// C++ control flow fixture: if, for, while, and range-based for loops.
#include <string>

int classify(int x) {
    if (x > 0) {
        return 1;
    } else if (x < 0) {
        return -1;
    } else {
        return 0;
    }
}

int sumTo(int n) {
    int total = 0;
    for (int i = 0; i < n; i++) {
        total = total + i;
    }
    return total;
}

void countdown(int start) {
    while (start > 0) {
        start = start - 1;
    }
}

int sumArray(int arr[], int len) {
    int sum = 0;
    for (int i = 0; i < len; i++) {
        sum = sum + arr[i];
    }
    return sum;
}

std::string joinWords(std::string words[], int count) {
    std::string result = "";
    for (int i = 0; i < count; i++) {
        result = result + words[i];
    }
    return result;
}
