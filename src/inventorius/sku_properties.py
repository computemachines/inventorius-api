"""The ordinary name property supplies the legacy SKU display/search value."""


def sku_display_name(props: dict | None, fallback: str | None = None) -> str | None:
    if props is None or "name" not in props:
        return fallback
    name = props["name"]
    if not isinstance(name, str):
        raise ValueError("SKU name property must be text")
    return name
