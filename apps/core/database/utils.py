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


def model_from_dict(model: type[SQLAlchemyModelT], **kwargs: dict[str, Any]) -> SQLAlchemyModelT:
    """Create an ORM model instance from a dictionary of attributes.

    Args:
        model: The SQLAlchemy model class to instantiate.
        **kwargs: Keyword arguments containing model attribute values.

    Returns:
        SQLAlchemyModelT: A new instance of the model populated with the provided values.
    """
    data = {
        column_name: kwargs[column_name]
        for column_name in model.__table__.columns.keys()  # noqa: SIM118
        if column_name in kwargs
    }

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
