def process(raw):
    cleaned = raw.strip()
    upper = cleaned.upper()
    return upper


def pipeline():
    data = "  hello  "
    result = process(data)
    print(result)
