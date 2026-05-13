import re
import unicodedata
from typing import Any, cast

from sqlalchemy.orm import InstrumentedAttribute

from .types import SQLAlchemyModelT


def get_instrumented_attr(
    model: type[SQLAlchemyModelT],
    key: str | InstrumentedAttribute[Any],
) -> InstrumentedAttribute[Any]:
    """Get an instrumented attribute from a model.

    Args:
        model: SQLAlchemy model class.
        key: Either a string attribute name or an :class:`sqlalchemy.orm.InstrumentedAttribute`.

    Returns:
        :class:`sqlalchemy.orm.InstrumentedAttribute`: The instrumented attribute from the model.
    """
    if isinstance(key, str):
        return cast("InstrumentedAttribute[Any]", getattr(model, key))
    return key


def model_from_dict(
    model: type[SQLAlchemyModelT],
    *,
    strict: bool = True,
    **kwargs: Any,
) -> SQLAlchemyModelT:
    """Create an ORM model instance from a dictionary of attributes.

    Args:
        model: The SQLAlchemy model class to instantiate.
        strict: When True (the default), raise :class:`TypeError` for any
            kwarg that is not a column of ``model``. When False, silently
            drop unknown kwargs — the pre-F-QUAL-1 behavior. Opt out only
            when filtering trusted-and-superset payloads.
        **kwargs: Keyword arguments containing model attribute values.

    Returns:
        SQLAlchemyModelT: A new instance of the model populated with the
        provided values.

    Raises:
        TypeError: If ``strict`` is True and ``kwargs`` contains a key
            that is not a mapped column of ``model``.
    """
    column_names = set(model.__table__.columns.keys())
    if strict:
        unknown = set(kwargs) - column_names
        if unknown:
            unknown_list = ", ".join(sorted(unknown))
            msg = f"model_from_dict: unknown attribute(s) {unknown_list!r} on {model.__name__}"
            raise TypeError(msg)

    data = {name: kwargs[name] for name in column_names if name in kwargs}
    return model(**data)


def slugify(value: str, *, allow_unicode: bool = False, separator: str | None = None) -> str:
    """Slugify.

    Convert to ASCII if ``allow_unicode`` is ``False``. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.

    Args:
        value (str): the string to slugify
        allow_unicode (bool, optional): allow unicode characters in slug. Defaults to False.
        separator (str, optional): by default a `-` is used to delimit word boundaries.
            Set this to configure something different.

    Returns:
        str: a slugified string of the value parameter
    """
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value.lower())
    if separator is not None:
        return re.sub(r"[-\s]+", "-", value).strip("-_").replace("-", separator)
    return re.sub(r"[-\s]+", "-", value).strip("-_")
