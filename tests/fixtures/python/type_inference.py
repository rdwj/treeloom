class Animal:
    def speak(self):
        return "..."

    def breathe(self):
        return "air"


class Dog(Animal):
    def speak(self):
        return "woof"

    def fetch(self):
        return "ball"


class Cat(Animal):
    def speak(self):
        return "meow"


def make_sounds():
    d = Dog()
    c = Cat()
    dog_sound = d.speak()
    cat_sound = c.speak()
    air = d.breathe()
    ball = d.fetch()
