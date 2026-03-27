fn outer(x: i32) -> i32 {
    let inner = |y: i32| -> i32 {
        x + y
    };
    inner(10)
}
