package main

func transform(input string) string {
	x := input
	y := x
	return y
}

func multiAssign(a, b string) string {
	result := a
	result = b
	return result
}

func multiReturn() (string, int) {
	return "hello", 42
}

func useMultiReturn() {
	s, n := multiReturn()
	_ = s
	_ = n
}
