package main

import "fmt"

import (
	"os"
	"strings"
)

func main() {
	fmt.Println(os.Args[0])
	_ = strings.Join(os.Args, " ")
}
