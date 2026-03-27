class Processor {
    private data: string;

    constructor(data: string) {
        this.data = data;
    }

    process(): string {
        return this.data;
    }

    validate(input: string): string {
        return input;
    }
}

function run(): string {
    const p = new Processor("test");
    const result = p.process();
    const valid = p.validate(result);
    return valid;
}
