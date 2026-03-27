function source() {
    return "tainted";
}

function passthrough(data) {
    return data;
}

function sink(value) {
    console.log(value);
}

function main() {
    const data = source();
    const processed = passthrough(data);
    sink(processed);
}
