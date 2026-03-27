int outer(int x) {
    auto inner = [x](int y) -> int {
        return x + y;
    };
    return inner(10);
}
