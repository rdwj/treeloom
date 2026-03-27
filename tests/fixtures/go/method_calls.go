package main

type Processor struct {
	Data string
}

func NewProcessor(data string) *Processor {
	return &Processor{Data: data}
}

func (p *Processor) Process() string {
	return p.Data
}

func (p *Processor) Validate(input string) string {
	return input
}

func run() {
	p := NewProcessor("test")
	result := p.Process()
	valid := p.Validate(result)
	_ = valid
}
