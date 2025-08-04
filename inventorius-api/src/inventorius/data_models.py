from email.policy import default
import json
from bson.decimal128 import Decimal128

# -------- Helper functions


def get_class_variables(cls):
    """Returns a list of class variables of interest. Filters out callable and dunder variables."""
    class_variables = []
    for attr in dir(cls):
        attr_value = getattr(cls, attr)
        if (not callable(attr_value) and
                not attr.startswith('__')):
            class_variables.append(attr)
        # elif isinstance(attr_value, type) and issubclass(attr_value, DataModel):
        #     class_variables.append(attr)
    return class_variables


def get_fields(cls):
    return [attr for attr in get_class_variables(cls)
            if issubclass(getattr(cls, attr).__class__, DataField) or issubclass(getattr(cls, attr).__class__, Subdoc)
            ]

# def get_subdocs(cls):
#     return list(filter(lambda attr: issubclass(getattr(cls, attr).__class__, DataModel),
#                        get_class_variables(cls)))

# -------- Utility classes


class DataModelJSONEncoder(json.JSONEncoder):
    def default(self, o):
        return {k: v for k, v in o.__dict__.items() if k != None}


def identity(x): return x


def bypass_decorator(special_value, f):
    def wrapped_function(value):
        if value == special_value:
            return special_value
        else:
            return f(value)
    return wrapped_function


class DataField():
    """An individual field of the DataModel.

    If db_key=None Then will not be retained when transformed to a mongodb doc.
    """

    def __init__(self, db_key=None, required=False, default=None, value_to_bson=identity, bson_to_value=identity, bypass_none=True):
        self.db_key = db_key
        self.required = required
        self.default = default
        if bypass_none:
            self.value_to_bson = bypass_decorator(None, value_to_bson)
            self.bson_to_value = bypass_decorator(None, bson_to_value)
        else:
            self.value_to_bson = value_to_bson
            self.bson_to_value = bson_to_value

    def __repr__(self):
        return f"DataField(db_key={self.db_key}, required={self.required}, default={self.default})"


class Subdoc():
    """A datafield that maps to a mongodb subdocument."""

    def __init__(self, db_key, data_model_type, default=None):
        self.data_model_type = data_model_type
        self.db_key = db_key
        if default is None:
            self.default = data_model_type()
        else:
            self.default = default


class DataModel():
    """Abstract base class for managing conversion between app data structures and
       mongodb bson documents.

       Subclasses must have `DataField` class variables.
    """

    def __init__(self, **kwargs):
        for field in get_class_variables(type(self)):
            class_variable = getattr(self.__class__, field)

            if isinstance(class_variable, DataField):
                # if field in kwargs:
                # then called like ChildModel(field=value) so then simulate dataclass
                #   types by setting self.<field> = kwargs[field] (also masking class variable)
                #
                #   sometimes called like ChildModel(field=None). in this case kwargs[field]
                #   is none. Don't treat this special. Don't use default. If I take the time
                #   to write field=None, assume I really want None.

                if kwargs.get(field) != None:
                    setattr(self, field, kwargs[field])
                #
                # elif class_variable.default is set: then self.<field> = field.default.copy()
                #
                # elif field.required: raise exception
                #
                # else: pass # field was not required and left undefined
                elif class_variable.required:
                    raise KeyError("'{}' is a required field in class '{}'".format(
                        field, self.__class__.__name__))
                elif class_variable.default != None and type(class_variable.default) == list:
                    setattr(self, field, class_variable.default.copy())
                elif class_variable.default != None:
                    setattr(self, field, class_variable.default)
                else:
                    setattr(self, field, None)

            elif isinstance(class_variable, Subdoc):
                if field in kwargs:
                    if type(kwargs[field]) is dict:
                        setattr(self, field, class_variable.data_model_type(
                            **kwargs[field]))
                    else:
                        setattr(self, field, kwargs[field])
                else:
                    if class_variable.default is not None and type(class_variable.default) is list:
                        setattr(self, field, class_variable.default.copy())
                    elif class_variable.default is not None:
                        setattr(self, field, class_variable.default)

    def __eq__(self, other):
        if type(self) != type(other):
            return False
        for field in get_class_variables(self):
            if getattr(self, field) != getattr(other, field):
                return False
        return True

    def to_json(self, mask_default=True):
        return json.dumps(self.to_dict(mask_default), cls=DataModelJSONEncoder)

    def __repr__(self):
        return f'{self.__class__.__name__}({", ".join("=".join((k, v.__repr__())) for k, v in self.__dict__.items() if k!=None)})'

    @classmethod
    def from_json(cls, json_str):
        if type(json_str) == str:
            return cls(**json.loads(json_str))
        else:
            return cls(**json_str)

    @classmethod
    def from_mongodb_doc(cls, mongo_dict):
        model_keys = get_fields(cls)

        def db_key_to_model_key(db_key):
            # search model_keys
            for model_key in model_keys:
                if getattr(cls, model_key).db_key == db_key:
                    return model_key
            if issubclass(cls, HasAdditionalFields):
                return db_key
            else:
                raise Exception(
                    "db_key not in DataModel schema, and class does not inherit HasAdditionalFields")

        def db_value_to_model_value(model_key, db_value):
            if not issubclass(cls, HasAdditionalFields):
                if not hasattr(cls, model_key):
                    raise Exception(
                        "db_key not in DataModel schema, and class does not inherit HasAdditionalFields")
                attribute = getattr(cls, model_key)
                if isinstance(attribute, DataField):
                    return attribute.bson_to_value(db_value)
                if isinstance(attribute, Subdoc):
                    return attribute.data_model_type.from_mongodb_doc(db_value)
            else:
                attribute = getattr(cls, model_key)
                return attribute.bson_to_value(db_value)
                # return db_value

        if mongo_dict is None:
            return None
        data_model_dict = {}
        for db_key, db_value in mongo_dict.items():
            model_key = db_key_to_model_key(db_key)
            model_value = db_value_to_model_value(
                model_key=model_key, db_value=db_value)
            if model_key in model_keys:
                data_model_dict[model_key] = model_value
        return cls(**data_model_dict)

    def to_mongodb_doc(self):
        model_keys = get_fields(type(self))

        def model_key_to_db_key(model_key):
            return getattr(self.__class__, model_key).db_key

        def model_value_to_db_value(model_key, model_value):
            attribute = getattr(self.__class__, model_key)
            if isinstance(attribute, DataField):
                return attribute.value_to_bson(model_value)
            if isinstance(attribute, Subdoc) \
                    and type(model_value) is not Subdoc:  # guard against undefined instance variables.
                return model_value.to_mongodb_doc()

        # transform self.__dict__ like {k: v} => {f(k): v}
        transformed_dict = {}
        for model_key in model_keys:

            # If a model_key is not an instance variable,
            # then getattr should return the value model_key in the subclass.
            model_value = getattr(self, model_key)

            # don't break the db schema
            assert getattr(type(self), model_key) != None

            db_key = model_key_to_db_key(model_key)
            db_value = model_value_to_db_value(model_key, model_value)

            if db_key is not None and type(db_value) != DataField:
                transformed_dict[db_key] = db_value
        return transformed_dict

    def to_dict(self, mask_default=False):
        prepared_dict = {}
        for key, value in self.__dict__.items():
            class_variable = getattr(type(self), key)
            if isinstance(class_variable, Subdoc):
                if type(value) == class_variable.data_model_type:
                    subdoc_dict = value.to_dict(mask_default)
                    default_dict = class_variable.default.to_dict(
                        mask_default=True)
                    if not mask_default or (mask_default and subdoc_dict != default_dict):
                        prepared_dict[key] = subdoc_dict
                assert type(value) is not dict

            elif isinstance(class_variable, DataField):
                if mask_default and value == class_variable.default:
                    # if value is default don't include it in the output
                    continue
                else:
                    # otherwise include the value in the output
                    prepared_dict[key] = value
        return prepared_dict

# -------- Data model flags


class HasAdditionalFields:
    pass


# -------- Data models for db

class UserData(DataModel):
    fixed_id = DataField("_id", required=True)
    shadow_id = DataField("shadow_id", required=True)
    password_hash = DataField("password_hash", required=True)
    password_salt = DataField("password_salt", required=True)
    active = DataField("active", default=False)
    # role = DataField("role")
    name = DataField("name")
    # email = DataField("email")


def currency_from_bson(units):
    assert units["unit"] == "USD"
    return {"unit": "USD", "value": float(units['value'].to_decimal())}


def currency_to_bson(units):
    assert units["unit"] == "USD"
    return {"unit": "USD", "value": Decimal128(str(units['value']))}


class Props(DataModel, HasAdditionalFields):
    cost_per_case = DataField(
        "cost_per_case", value_to_bson=currency_to_bson, bson_to_value=currency_from_bson)
    count_per_case = DataField("count_per_case")
    original_cost_per_case = DataField(
        "original_cost_per_case", value_to_bson=currency_to_bson, bson_to_value=currency_from_bson)
    original_count_per_case = DataField("original_count_per_case")


class Bin(DataModel):
    """Models a physical bin in the inventory system."""
    # if a datafield does not have a db_key set then it should not be stored as a db field
    id = DataField("_id", required=True)
    props = DataField("props")
    # _contents = [{id: label, quantity: n}]
    contents = DataField("contents", default={})
    # unit_count = DataField()
    # sku_count = DataField()

    # def contentsMap(self, key=None):
    #     out = {e['id']: e['quantity'] for e in self.contents}
    #     if key:
    #         return out[key]
    #     return out


class Sku(DataModel):
    id = DataField("_id", required=True)
    owned_codes = DataField("owned_codes", default=[])
    associated_codes = DataField("associated_codes", default=[])
    name = DataField("name")
    # average_unit_original_cost = DataField("average_unit_original_cost")
    # average_unit_asset_value = DataField()
    props = DataField("props")


class Batch(DataModel):
    id = DataField("_id", required=True)
    sku_id = DataField("sku_id")
    name = DataField("name")
    owned_codes = DataField("owned_codes", default=[])
    associated_codes = DataField("associated_codes", default=[])
    # props = DataField("props")
    props = Subdoc("props", Props)
    # parent_id = DataField("parent_id")
    # original_cost = DataField()
    # original_cost_per_unit = DataField()
    # asset_value = DataField()
    # asset_value_per_unit = DataField()
    # unit_count = DataField()
    # assembly = DataField()
    # assembly_date = DataField()
    # expiration_date = DataField()
    # inherited_props = DataField()
