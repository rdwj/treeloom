def check(x):
    if x > 10:
        print("big")
    elif x > 5:
        print("medium")
    else:
        print("small")

    for i in range(x):
        print(i)

    while x > 0:
        x = x - 1
