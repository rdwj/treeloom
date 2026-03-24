fn classify(n: i32) -> i32 {
    if n > 0 {
        return 1;
    } else if n < 0 {
        return -1;
    } else {
        return 0;
    }
}

fn sum_range(limit: i32) -> i32 {
    let mut total = 0;
    for i in 0..limit {
        total = total + i;
    }
    return total;
}

fn count_down(start: i32) -> i32 {
    let mut n = start;
    while n > 0 {
        n = n - 1;
    }
    return n;
}

fn first_even(items: i32) -> i32 {
    let mut i = 0;
    loop {
        if i % 2 == 0 {
            return i;
        }
        i = i + 1;
    }
}

fn label(n: i32) -> i32 {
    match n {
        1 => 10,
        2 => 20,
        _ => 0,
    }
}
