from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using a key in templates."""
    if dictionary is None:
        return None
    return dictionary.get(key)
