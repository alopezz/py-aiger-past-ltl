from uuid import uuid1

import aiger
import funcy as fn
from lenses import bind

from parsimonious import Grammar, NodeVisitor
import hypothesis.strategies as st
from hypothesis_cfg import ContextFreeGrammarStrategy


PLTL_GRAMMAR = Grammar(u'''
phi =  since / or / and / implies / hist / past / vyest / neg 
     / true / false / AP
or = "(" _ phi _ "|" _ phi _ ")"
implies = "(" _ phi _ "->" _ phi _ ")"
and = "(" _ phi _ "&" _ phi _ ")"
hist = "H" _ phi
past = "P" _ phi
vyest = "Z" _ phi
since = "[" _ phi _ "S" _ phi _ "]"
neg = "~" _ phi
true = "TRUE"
false = "FALSE"

_ = ~r" "*
AP = ~r"[a-zA-z]" ~r"[a-zA-Z\d]*"
EOL = "\\n"
''')


class PTLTLExpr(aiger.BoolExpr):
    def __call__(self, trc):
        if isinstance(trc, list):
            val, _ = self.aig.simulate(trc)[-1]
            return val[self.output]
        else:
            return aiger.BoolExpr.__call__(self, trc)

    def historically(self):
        return PTLTLExpr(self.aig >> hist_monitor(self.output))

    def once(self):
        return PTLTLExpr(self.aig >> past_monitor(self.output))

    def vyest(self):
        return PTLTLExpr(self.aig >> vyest_monitor(self.output))

    def since(self, other):
        monitor = since_monitor(self.output, other.output)
        return PTLTLExpr((self.aig | other.aig) >> monitor)


class PLTLVisitor(NodeVisitor):
    def generic_visit(self, _, children):
        return children

    def visit_phi(self, _, children):
        return children[0]

    def visit_AP(self, node, _):
        return PTLTLExpr(aiger.atom(node.text).aig)

    def visit_and(self, _, children):
        return children[2] & children[6]

    def visit_or(self, _, children):
        return children[2] | children[6]

    def visit_neg(self, _, children):
        return ~children[2]

    def visit_implies(self, _, children):
        return children[2].implies(children[6])

    def visit_vyest(self, _, children):
        return children[2].vyest()

    def visit_hist(self, _, children):
        return children[2].historically()

    def visit_past(self, _, children):
        return children[2].once()
    
    def visit_since(self, _, children):
        return children[2].since(children[6])

    def visit_true(self, *_):
        return PTLTLExpr(aiger.atom(True).aig)

    def visit_false(self, *_):
        return PTLTLExpr(aiger.atom(False).aig)


def vyest_monitor(name):
    return aiger.delay(
        inputs=[name],
        initials=[True],
        latches=[aiger.common._fresh()],
        outputs=[aiger.common._fresh()]
    )


def hist_monitor(name):
    out = aiger.common._fresh()
    return aiger.and_gate([name, 'tmp'], out).feedback(
        inputs=['tmp'],
        outputs=[out],
        latches=[aiger.common._fresh()],
        initials=[True],
        keep_outputs=True
    )


def past_monitor(name):
    out = aiger.common._fresh()
    return aiger.or_gate([name, 'tmp'], out).feedback(
        inputs=['tmp'],
        outputs=[out],
        latches=[aiger.common._fresh()],
        initials=[False],
        keep_outputs=True
    )


def since_monitor(left, right):
    tmp = aiger.common._fresh()
    left, right = aiger.atom(left), aiger.atom(right)
    active = aiger.atom(tmp)
    update = active.implies(left | right) & (~active).implies(right)

    circ = update.aig['o', {update.output: tmp}]
    return circ.feedback(
        inputs=[tmp],
        outputs=[tmp],
        latches=[aiger.common._fresh()],
        initials=[False],
        keep_outputs=True,
    )


def parse(pltl_str: str, output=None):
    expr = PLTLVisitor().visit(PLTL_GRAMMAR.parse(pltl_str))
    aig = expr.aig.evolve(comments=(pltl_str,))
    if output is not None:
        aig = aig['o', {expr.output: output}]

    return type(expr)(aig)
