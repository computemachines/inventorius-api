import json

# -------- Helper functions


def get_class_variables(cls):
    class_variables = []
    for attr in dir(cls):
        if (not callable(getattr(cls, attr)) and
                not attr.startswith('__')):
            class_variables.append(attr)
    return class_variables


def get_fields(cls):
    return list(filter(lambda attr: issubclass(getattr(cls, attr).__class__, DataField),
                       get_class_variables(cls)))

# -------- Utility classes


class DataModelJSONEncoder(json.JSONEncoder):
    def default(self, o):
        return {k: v for k, v in o.__dict__.items() if k != None}


class DataField():
    """An individual field of the DataModel.

    If db_key=None Then will not be retained when transformed to a mongodb doc.
    """

    def __init__(self, db_key=None, required=False, default=None):
        self.db_key = db_key
        self.required = required
        self.default = default

    def __repr__(self):
        return f"DataField(db_key={self.db_key}, required={self.required}, default={self.default})"


class DataModel():
    """Abstract base class for managing conversion between app data structures and
       mongodb bson documents.

       Subclasses must have `DataField` class variables.
    """

    def __init__(self, **kwargs):
        for field in get_class_variables(type(self)):
            class_variable = getattr(self.__class__, field)

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

    def __eq__(self, other):
        if type(self) != type(other):
            return False
        for field in get_class_variables(self):
            if getattr(self, field) != getattr(other, field):
                return False
        return True

    def to_json(self, mask_none=True):
        return json.dumps(self.to_dict(mask_none), cls=DataModelJSONEncoder)

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

        def find_model_key_from_db_key(db_key):
            for model_key in model_keys:
                if getattr(cls, model_key).db_key == db_key:
                    return model_key
        if mongo_dict is None:
            return None
        data_model_dict = {}
        for db_key, v in mongo_dict.items():
            model_key = find_model_key_from_db_key(db_key)
            if model_key in model_keys:
                data_model_dict[model_key] = v
        return cls(**data_model_dict)

    def to_mongodb_doc(self):
        model_keys = get_fields(type(self))

        def model_key_to_db_key(model_key):
            return getattr(self.__class__, model_key).db_key

        # transform self.__dict__ like {k: v} => {f(k): v}
        transformed_dict = {}
        for model_key in model_keys:

            # If a model_key is not an instance variable,
            # then getattr should return the value model_key in the subclass.
            model_value = getattr(self, model_key)

            # don't break the db schema
            assert getattr(type(self), model_key) != None

            db_key = model_key_to_db_key(model_key)

            if db_key is not None and type(model_value) != DataField:
                transformed_dict[db_key] = model_value
        return transformed_dict

    def to_dict(self, mask_none=False):
        if mask_none:
            return {k: v for k, v in self.__dict__.items() if v != None}
        else:
            return self.__dict__

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
    props = DataField("props")
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
