function check(value) {
    if (value > 10) {
        console.log("big");
    } else if (value > 5) {
        console.log("medium");
    } else {
        console.log("small");
    }

    for (let i = 0; i < value; i++) {
        console.log(i);
    }

    let count = 0;
    while (count < 3) {
        console.log(count);
        count = count + 1;
    }
}
