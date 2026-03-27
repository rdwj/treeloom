function source(): string {
    return "tainted";
}

function passthrough(data: string): string {
    return data;
}

function sink(value: string): void {
    console.log(value);
}

function main(): void {
    const data = source();
    const processed = passthrough(data);
    sink(processed);
}
