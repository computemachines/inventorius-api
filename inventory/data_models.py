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

class MyEncoder(json.JSONEncoder):
    def default(self, o):
        return {k: v for k, v in o.__dict__.items() if v is not None}

class DataField():
    def __init__(self, db_key=None, required=False, default=None):
        self.db_key = db_key
        self.required = required
        self.default = default
        
class DataModel():
    def __init__(self, **kwargs):
        for field in get_fields(type(self)):
            instance_field = getattr(self.__class__, field)
            if field not in kwargs and not instance_field.required:
                setattr(self, field, instance_field.default)
            else:
                setattr(self, field, kwargs[field])
    
    def to_json(self):
        return json.dumps(self, cls=MyEncoder)

    def __repr__(self):
        return f'{self.__class__.__name__}({self.to_json()})'
    
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

        transformed_dict = {}
        for model_key in model_keys:
            model_value = getattr(self, model_key)
            db_key = model_key_to_db_key(model_key)
            if db_key is not None and model_value is not None:
                transformed_dict[db_key] = model_value
        return transformed_dict
    
# -------- Data models for db
                           
class Bin(DataModel):
    # if a datafield does not have a db_key set then it should not be stored in the db
    id = DataField("id", required=True)
    props = DataField("props")
    contents = DataField("contents", default=[]) # [{<type>_id: ID, quantity: n}]
    unit_count = DataField()
    sku_count = DataField()
    def skus(self):
        return {e['sku_id']: e['quantity'] for e in self.contents if 'sku_id' in e}
    
class Sku(DataModel):
    id = DataField("id", required=True)
    owned_codes = DataField("owned_codes", required=True)
    name = DataField("name", required=True)
    average_unit_original_cost = DataField("average_unit_original_cost")
    average_unit_asset_value = DataField()
    props = DataField("props")

class Batch(DataModel):
    id = DataField("id", required=True)
    sku_id = DataField("sku_id")
    original_cost = DataField()
    original_cost_per_unit = DataField()
    asset_value = DataField()
    asset_value_per_unit = DataField()
    unit_count = DataField()
    assembly = DataField()
    assembly_date = DataField()
    expiration_date = DataField()
    props = DataField("props")

class Uniq(DataModel):
    id = DataField("id", required=True)
    bin_id = DataField("bin_id", required=True)
    sku_parent = DataField("sku_id")
    name = DataField("name")
    original_cost = DataField("original_cost")
    asset_value = DataField("asset_value")
    assembly = DataField()
    props = DataField("props")

# class BinExtended:
#     def __init__(self, json=None):
#         self._id = json['id']
#         self.props = json.get('props', None)
#         self.contents = json.get('contents', None)

#     def toJson(self):
#         return json.dumps(self, cls=MyEncoder)

#     def toDict(self):
#         d = {'id': self._id}
#         if self.props is not None:
#             d['props'] = self.props
#         if self.contents is not None:
#             d['contents'] = self.contents
#         return d

# class SKU:
#     def __init__(self, json):
#         self._id = json['id']
#         self.owned_codes = json['owned codes']
#         self.name = json['name']

#     def toDict(self):
#         d = {'id': self._id,
#              'name': self.name,
#              'owned codes': self.owned_codes}
#         return d

#     def toJson(self):
#         return json.dumps(self, cls=MyEncoder)
    
