def flask_handler():
    username = request.form.get('username')
    password = request.form.get('password')
    result = login(username, password)
    execute(result)


def dict_access():
    data = config['database']
    connect(data)


def chained_method():
    value = obj.method().strip()
    process(value)


def attr_access():
    value = obj.attr
    use(value)
