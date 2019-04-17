import json

class Bin:
    def __init__(self, json=None):
        self._id = json['id']
        self.props = json.get('props', {})
        
    def __str__(self):
        return "Bin(id={}, props={})".format(self._id, self.props)

    def __eq__(self, other):
        return self._id == other._id and self.props == other.props

    def toJson(self):
        return json.dumps(self, cls=MyEncoder)

    def toDict(self):
        return {'id': self._id, 'props': self.props}

class MyEncoder(json.JSONEncoder):
    def default(self, o):
        return o.toDict()
