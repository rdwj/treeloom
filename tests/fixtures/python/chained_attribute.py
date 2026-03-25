"""Fixture: chained attribute access for DFG and field-sensitivity tests."""


def handle_request(request):
    # Chained attribute: request.form is an attribute, .get is a method call.
    # Data should flow: request -> request.form -> get('username')
    username = request.form.get("username")
    return username


def field_sensitivity(obj):
    # request.safe_field and request.unsafe_field are separate DFG chains.
    x = obj.safe_field
    y = obj.unsafe_field
    return x, y
