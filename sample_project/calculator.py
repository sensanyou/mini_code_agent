def add(a, b):
    return a + b


def divide(a, b):
    # Intentionally imperfect for the Agent to discover.
    if b == 0:
        return 0
    return a / b
