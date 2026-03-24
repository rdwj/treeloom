use std::fmt;

struct Rectangle {
    width: f64,
    height: f64,
}

impl Rectangle {
    fn new(width: f64, height: f64) -> Rectangle {
        Rectangle { width, height }
    }

    fn area(&self) -> f64 {
        let w = self.width;
        let h = self.height;
        w * h
    }

    fn describe(&self) -> String {
        String::from("rectangle")
    }
}

fn make_rect(w: f64, h: f64) -> Rectangle {
    Rectangle::new(w, h)
}
