package main

import "fmt"

func source() string {
	return "tainted"
}

func passthrough(data string) string {
	return data
}

func sink(value string) {
	fmt.Println(value)
}

func main() {
	data := source()
	processed := passthrough(data)
	sink(processed)
}
