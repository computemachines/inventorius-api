from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule, precondition
import hypothesis.strategies as st


class MyStack(object):
    def __init__(self):
        self.stack = []
        self.holding = None
        self.len = 0

    def hold(self, v):
        self.holding = v

    def push(self):
        self.stack.append(self.holding)
        self.holding = None
        self.len += 1

    def pop(self):
        self.len -= 1
        return self.stack.pop()


class LearningState(RuleBasedStateMachine):
    def __init__(self):
        super(LearningState, self).__init__()
        self.stack = MyStack()
        self.model = []
        self.staging = None

    @rule(v=st.integers())
    def hold_value(self, v):
        self.stack.hold(v)
        self.staging = v

    @precondition(lambda self: self.staging)
    @rule()
    def push_value(self):
        self.model.append(self.staging)
        self.staging = None
        self.stack.push()

    @rule()
    def lengths_agree(self):
        assert self.stack.len == len(self.model)

    @precondition(lambda self: self.stack.len != 0 and len(self.model))
    @rule()
    def pop_agrees(self):
        assert self.stack.pop() == self.model.pop()

    def teardown(self):
        pass


LearningStateTest = LearningState.TestCase
