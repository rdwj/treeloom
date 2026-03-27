function outer(x) {
    function inner(y) {
        return x + y;
    }
    return inner(10);
}

const closure = (function() {
    let count = 0;
    return function increment() {
        count += 1;
        return count;
    };
})();
