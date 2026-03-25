def format_method(username, password):
    query = "SELECT * WHERE u='{}' AND p='{}'".format(username, password)
    return query


def percent_format(username):
    query = "SELECT * WHERE u='%s'" % username
    return query


def fstring_format(username):
    query = f"SELECT * WHERE u='{username}'"
    return query


def nested_format(username, password):
    c = get_cursor()
    c.execute("SELECT * WHERE u='{}' AND p='{}'".format(username, password))


def percent_tuple(username, password):
    query = "SELECT * WHERE u='%s' AND p='%s'" % (username, password)
    return query
