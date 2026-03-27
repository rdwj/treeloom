struct Processor {
    data: String,
}

impl Processor {
    fn new(data: String) -> Self {
        Processor { data }
    }

    fn process(&self) -> &str {
        &self.data
    }

    fn validate(&self, input: &str) -> &str {
        input
    }
}

fn run() {
    let p = Processor::new(String::from("test"));
    let result = p.process();
    let valid = p.validate(result);
    let _ = valid;
}
