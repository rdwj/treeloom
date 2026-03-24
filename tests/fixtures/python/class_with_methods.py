class Calculator:
    def __init__(self, value):
        self.value = value

    def add(self, n):
        self.value = self.value + n
        return self.value

    def reset(self):
        self.value = 0
