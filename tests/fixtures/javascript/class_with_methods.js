class Calculator {
    constructor(initial) {
        this.value = initial;
    }

    add(n) {
        this.value = this.value + n;
        return this.value;
    }

    reset() {
        this.value = 0;
    }
}
