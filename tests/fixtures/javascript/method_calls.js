class Processor {
    constructor(data) {
        this.data = data;
    }

    process() {
        return this.data;
    }

    validate(input) {
        return input;
    }
}

function run() {
    const p = new Processor("test");
    const result = p.process();
    const valid = p.validate(result);
    return valid;
}
