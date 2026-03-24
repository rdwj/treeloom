#include <stdio.h>

void check(int value) {
    if (value > 100) {
        printf("large\n");
    } else {
        printf("small\n");
    }

    for (int i = 0; i < value; i++) {
        printf("%d\n", i);
    }

    int n = value;
    while (n > 0) {
        n = n - 1;
    }
}
