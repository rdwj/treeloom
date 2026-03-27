typedef int (*operation)(int, int);

int add(int a, int b) {
    return a + b;
}

int apply(operation op, int x, int y) {
    return op(x, y);
}

int main(void) {
    int result = apply(add, 3, 4);
    return result;
}
