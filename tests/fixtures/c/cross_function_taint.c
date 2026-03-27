#include <stdio.h>

char* source(void) {
    return "tainted";
}

char* passthrough(char* data) {
    return data;
}

void sink(char* value) {
    printf("%s\n", value);
}

int main(void) {
    char* data = source();
    char* processed = passthrough(data);
    sink(processed);
    return 0;
}
