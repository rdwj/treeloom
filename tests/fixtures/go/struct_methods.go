package main

import "fmt"

type Rectangle struct {
	Width  float64
	Height float64
}

func NewRectangle(w float64, h float64) Rectangle {
	r := Rectangle{}
	return r
}

func (r Rectangle) Area() float64 {
	area := r.Width * r.Height
	return area
}

func (r Rectangle) Describe() string {
	desc := fmt.Sprintf("rect %f x %f", r.Width, r.Height)
	return desc
}
