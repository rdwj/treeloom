package main

func outer(x int) int {
	inner := func(y int) int {
		return x + y
	}
	return inner(10)
}

func withDefer() {
	defer func() {
		recover()
	}()
}
