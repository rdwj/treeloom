package main

import "fmt"

func classify(n int) string {
	if n < 0 {
		return "negative"
	} else if n == 0 {
		return "zero"
	} else {
		return "positive"
	}
}

func sumTo(n int) int {
	total := 0
	for i := 0; i < n; i++ {
		total = total + i
	}
	return total
}

func printItems(items []string) {
	for _, item := range items {
		fmt.Println(item)
	}
}
