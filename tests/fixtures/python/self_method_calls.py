class Calculator:
    def __init__(self):
        self.value = 0

    def add(self, x):
        self.value = self.value + x
        return self

    def reset(self):
        self.value = 0

    def compute(self):
        self.reset()
        self.add(10)
        return self.value


class AdvancedCalc(Calculator):
    def multiply(self, x):
        self.value = self.value * x

    def compute(self):
        self.reset()
        self.add(5)
        self.multiply(3)
        return self.value
