"""Fixture: taint flows across function boundaries.

Scenario: route handler passes user input to a utility function
that passes it to a dangerous call.
"""


def process_query(query):
    """Utility that passes its argument to a dangerous call."""
    result = execute_raw(query)
    return result


def execute_raw(sql):
    """Simulates executing a raw SQL query."""
    return eval(sql)


def handler(user_input):
    """Entry point: receives user input and calls process_query."""
    output = process_query(user_input)
    return output
