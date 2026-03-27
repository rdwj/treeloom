function outer(x: number): number {
    function inner(y: number): number {
        return x + y;
    }
    return inner(10);
}

const adder = (a: number) => (b: number): number => a + b;
