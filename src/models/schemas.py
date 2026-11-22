from typing import Annotated, Any, ClassVar, Generic, Optional, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel, BeforeValidator, ConfigDict, WithJsonSchema, model_serializer


# ---------------------------------------------------------------------------
# Shared field types for response models
# ---------------------------------------------------------------------------

# A JSON number that keeps ints as ints and floats as floats on the wire
# (a plain `float` field would turn 5 into 5.0).
Number = Annotated[Union[int, float], WithJsonSchema({"type": "number"})]

# A string read from Redis INFO. redis-py turns INFO values that look numeric
# into int/float, so a string-valued field may arrive as a number; coerce it
# back instead of failing response validation.
InfoStr = Annotated[str, BeforeValidator(lambda v: v if isinstance(v, str) else str(v))]


# ---------------------------------------------------------------------------
# Base class for response models
# ---------------------------------------------------------------------------

def _drop_additional_properties(schema: dict[str, Any]) -> None:
    schema.pop("additionalProperties", None)


class ResponseModel(BaseModel):
    """
    Base for the `data` payload models.

    Fields the service returns that a model does not declare are passed
    through rather than dropped, so a missed field can never disappear from
    a response. The JSON schema leaves `additionalProperties` unset, which is
    how JSON Schema already allows extra keys, so code generators do not add
    an index signature to every type.

    Fields named in `_omit_if_unset` are only present in some responses: they
    are left out of the output when the service did not return them, instead
    of being emitted as null.
    """

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        json_schema_extra=_drop_additional_properties,
    )

    _omit_if_unset: ClassVar[frozenset[str]] = frozenset()

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        data = handler(self)
        for name in self._omit_if_unset:
            if name not in self.model_fields_set:
                field = type(self).model_fields[name]
                data.pop(field.serialization_alias or field.alias or name, None)
        return data


# ---------------------------------------------------------------------------
# Generic envelope
# ---------------------------------------------------------------------------

T = TypeVar("T")


def _type_name(tp: Any) -> str:
    origin = get_origin(tp)
    if origin is list:
        return f"{_type_name(get_args(tp)[0])}List"
    if origin is dict:
        return f"{_type_name(get_args(tp)[1])}Map"
    if origin is Union:
        return "Or".join(_type_name(a) for a in get_args(tp) if a is not type(None))
    if tp is Any:
        return "Any"
    if tp in (str, int, float, bool):
        return tp.__name__.capitalize()
    return tp.__name__


class APIResponse(BaseModel, Generic[T]):
    """
    Standard envelope. Routes declare `response_model=api_response(SomeModel)`
    so the OpenAPI spec describes `data`; they still return the plain
    `APIResponse(data=...)`, which FastAPI validates against the declared model.
    """

    data: T
    error: Optional[dict] = None


_envelopes: dict[str, type[APIResponse]] = {}


def api_response(payload: Any, name: Optional[str] = None) -> type[APIResponse]:
    """
    `APIResponse[payload]` under a readable schema name, e.g. `KeyDetailResponse`
    or `ClientInfoListResponse` (pydantic would name it `APIResponse_KeyDetail_`).
    Pass `name` for payloads without a model of their own, such as plain dicts.
    """
    cls_name = f"{name or _type_name(payload)}Response"
    if cls_name not in _envelopes:
        _envelopes[cls_name] = type(cls_name, (APIResponse[payload],), {"__module__": __name__})
    return _envelopes[cls_name]
