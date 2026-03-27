fn source() -> String {
    String::from("tainted")
}

fn passthrough(data: String) -> String {
    data
}

fn sink(value: &str) {
    println!("{}", value);
}

fn main() {
    let data = source();
    let processed = passthrough(data);
    sink(&processed);
}
