import json

class Bin:
    def __init__(self, json=None):
        self._id = json['id']
        self.props = json['props']
        
    def __str__(self):
        return "Bin(id={}, props={})".format(self._id, self.props)

    def toJson(self):
        return '{{"id": "{}", "props": {}}}'.format(self._id, self.props)

class MyEncoder(json.JSONEncoder):
    def default(self, o):
        return {'id': o._id, 'props': o.props}
