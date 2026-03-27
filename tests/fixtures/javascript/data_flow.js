function transform(input) {
    let x = input;
    let y = x;
    return y;
}

function multiAssign(a, b) {
    let result = a;
    result = b;
    return result;
}

const value = transform("hello");
const output = multiAssign(value, "world");
