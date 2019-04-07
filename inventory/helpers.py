
class Bin:
    def __init__(self, json=None):
        self._id = json['id']
        self.props = json['props']
        
    def __repr__(self):
        return "Bin(id={}, props={})".format(self._id, self.props)
