def outer():
    x = "tainted"

    def inner():
        x = "safe"
        return x

    return x


def shadowing():
    data = "input"

    def helper():
        data = "cleaned"
        process(data)

    dangerous(data)
