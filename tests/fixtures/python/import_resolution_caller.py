from import_resolution_lib import helper, transform


def process(raw):
    cleaned = helper(raw)
    result = transform(cleaned)
    return result
