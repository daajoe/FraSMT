#!/usr/bin/env python
#
# Copyright 2018, 2019, 2020

#
# fhtw.py is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.  fhtw.py is distributed in
# the hope that it will be useful, but WITHOUT ANY WARRANTY; without
# even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.  You should have received a copy of the GNU General Public
# License along with fhtw.py.  If not, see
# <http://www.gnu.org/licenses/>.

from __future__ import absolute_import

import random
import logging
import os
import re
import subprocess
import tempfile
import time
from fractions import Fraction
# import htd_validate
from io import StringIO
from itertools import combinations

# noinspection PyUnresolvedReferences
from htd_validate.decompositions import FractionalHypertreeDecomposition

from lib.htd_validate.htd_validate.decompositions import FractionalHypertreeDecomposition


# TODO: make more general so that we can call multiple solvers
class FractionalHypertreeDecompositionCommandline(object):
    def __init__(self, hypergraph, wprecision=20, timeout=0, stream=None, checker_epsilon=None, ghtd=False,
                 solver_bin=None, debug=False, odebug=None):
        if stream is None:
            stream = StringIO()
        self._debug = debug
        self._odebug = odebug
        if solver_bin is None:
            logging.error("Solver binary not given. Exiting...")
            raise RuntimeError
        else:
            solver_bin = os.path.expanduser(solver_bin)
            if not os.path.isfile(solver_bin):
                logging.error(f"File {solver_bin} does not exist. Exiting...")
                exit(1)
            if not os.access(solver_bin, os.X_OK):
                logging.error(f"File {solver_bin} is not executable. Exiting...")
                exit(1)
            logging.info(f"===============================================================")
            logging.info(f"Using solver {solver_bin}.")
            logging.info(f"===============================================================")
            self.solver_bin = solver_bin

        if not checker_epsilon:
            checker_epsilon = Fraction(0.001)
        self.__checker_epsilon = Fraction(checker_epsilon)
        self.hypergraph = hypergraph
        self.num_vars = 0
        self.num_cls = 0
        self.timeout = timeout
        self.ord = None
        self.arc = None
        self.weight = None
        self.last = None
        self.bb = None
        self.l = None
        self.od = None
        self.top_ord = None
        self.top_ord_rev = None
        self.smallest = None

        self.__clauses = []
        self._vartab = {}
        self.stream = stream
        self.cards = []
        self.wprecision = wprecision
        self.stream.write('(set-logic QF_LRA)\n(set-option :print-success true)\n(set-option :produce-models true)\n')
        self.ghtd = ghtd

    def prepare_vars(self, topsort=0, clique=None):
        n = self.hypergraph.number_of_nodes()
        m = self.hypergraph.number_of_edges()

        # self.ord = np.zeros((n + 1, n + 1), dtype=int)
        self.ord = [[None for j in range(n + 1)] for i in range(n + 1)]
        # ordering
        for i in range(1, n + 1):
            # TODO: so far more variables
            for j in range(i + 1, n + 1):
                # for j in range(i + 1, n + 1):
                # (declare-const ord_ij Bool)
                #if i < j:
                self.ord[i][j] = self.add_var(name=f'ord_{i}_{j}')
                self.ord[j][i] = -self.ord[i][j] #None
                self.stream.write(f"(declare-const ord_{i}_{j} Bool)\n")

        # print self.hypergraph.nodes()
        # print n
        # print len(self.ord)
        # print self.ord
        # print self.hypergraph.edges()
        # exit(1)

        # arcs
        self.arc = [[None for j in range(n + 1)] for i in range(n + 1)]
        # self.arc = np.zeros((n + 1, n + 1), dtype=int)
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                # declare arc_ij variables
                self.arc[i][j] = self.add_var(name='arc_%s_%s' % (i, j))
                self.stream.write(f"(declare-const arc_{i}_{j} Bool)\n")

        # weights
        self.weight = [[None for ej in range(m + 1)]
                       for j in range(n + 1)]

        for j in range(1, n + 1):
            for ej in range(1, m + 1):
                # (declare-const weight_j_e Real)
                self.weight[j][ej] = self.add_var(name='weight_%s_e%s' % (j, ej))
                if self.ghtd:
                    self.stream.write(f"(declare-const weight_{j}_e{ej} Int)\n")
                else:
                    self.stream.write(f"(declare-const weight_{j}_e{ej} Real)\n")

                self.stream.write(f"(assert (<= weight_{j}_e{ej} 1))\n")
                self.stream.write(f"(assert (>= weight_{j}_e{ej} 0))\n")

        if topsort > 0:
            # compute a lexicographic ordering, taking care of clique symmetry breaking also
            vars = set(range(1, n + 1))
            if clique is not None and len(clique) > 0:
                vars.difference_update(clique)
            self.top_ord = [None]
            self.top_ord.extend(random.sample(vars, len(vars)))
            if clique is not None and len(clique) > 0:
                self.top_ord.extend(random.sample(clique, len(clique)))
            self.top_ord_rev = {self.top_ord[i]:i for i in range(1,n+1)}

            self.last = [None]
            if clique and len(clique) == 0: #dynamic clique symm breaking
                self.l = [None]
                self.bb = [None]
                self.od = [None]
            for i in range(1, n+1):
                self.last.append(self.add_var(name=f'last_{i}'))
                self.stream.write(f"(declare-const last_{i} Bool)\n")
                # vars for dynamic clique symm breaking
                if clique and len(clique) == 0:
                    self.l.append(self.add_var(name=f'l_{i}'))
                    self.stream.write(f"(declare-const l_{i} Bool)\n")
                    self.od.append(self.add_var(name=f'od_{i}'))
                    self.stream.write(f"(declare-const od_{i} Int)\n")
                    self.bb.append(self.add_var(name=f'bb_{i}'))
                    self.stream.write(f"(declare-const bb_{i} Bool)\n")

            self.smallest = [[]]
            # ordering
            for i in range(1, n + 1):
                self.smallest.append([None])
                for j in range(1, n + 1):
                    # for j in range(i + 1, n + 1):
                    # (declare-const ord_ij Bool)
                    self.smallest[i].append(None)
                    self.smallest[i][j] = self.add_var(name=f'smallest_{i}_{j}')
                    self.stream.write(f"(declare-const smallest_{i}_{j} Bool)\n")

    # z3.Real
    def add_var(self, name):
        self.num_vars += 1
        vid = self.num_vars
        self._vartab[vid] = name
        return vid

    def add_cards(self, C):
        self.cards.append(C)

    def literal(self, x):
        logging.debug("Literal %s (var: %s)" % (x, self._vartab[abs(x)]))
        return Not(self._vartab[abs(x)]) if x < 0 else self._vartab.get(x)

    def literal_str(self, x):
        if x < 0:
            ret = '(not %s)' % self._vartab[abs(x)]
        else:
            ret = '%s' % self._vartab.get(x)
        return ret

    def literal_list(self, C):
        return ' '.join([self.literal_str(x) for x in C])

    def add_clause(self, C):
        # C = map(neg, C)
        # self.stream.write("%s 0\n" %" ".join(map(str,C)))
        self.stream.write("(assert (or %s))\n" % (' '.join([self.literal_str(x) for x in C])))
        self.num_cls += 1

    # prepare variables
    def fractional_counters(self, m=None):
        n = self.hypergraph.number_of_nodes()

        logging.info("Counter for fractional covers value=%s" % m)
        for j in range(1, n + 1):
            C0 = []
            weights = []
            for e in self.hypergraph.edges():
                assert (e > 0)
                C0.append(self.weight[j][e])
                weights.append("weight_{j}_e{e}".format(j=j, e=e))

            # set optimization variable or value for SAT check
            # C = [self.literal(x) for x in C0]
            # f = (Sum(C) <= m)
            # logging.debug("Assertation %s" % f)
            # self.__solver.add(f)
            # set optimization variable or value for SAT check
            if m is None:
                m = 'm'
                if self.ghtd:
                    self.stream.write("(declare-const m Int)\n")
                else:
                    self.stream.write("(declare-const m Real)\n")
            if len(weights) > 1:
                self.stream.write(
                    "(assert ( <= (+ {weights}) {m}))\n".format(weights=" ".join(weights), m=m))
            elif len(weights) == 1:
                self.stream.write(f"(assert (<= {weights[0]} {m}))\n")

    #def ordf(self, i, j):
    #    return self.ord[i][j] if i < j else -self.ord[j][i]

    def elimination_ordering(self, n):
        logging.info('Ordering')
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                if i == j:
                    continue
                for l in range(1, n + 1):
                    if i == l or j == l:
                        continue
                    # OLD VERSION
                    #C = [-self.ord[i][j] if i < j else self.ord[j][i], -self.ord[j][l] if j < l else self.ord[l][j],
                    #     self.ord[i][l] if i < l else -self.ord[l][i]]
                    C = [-self.ord[i][j], -self.ord[j][l], self.ord[i][l]]
                    self.add_clause(C)

        logging.info('Edges')
        # OLD VERSION
        # for e in self.hypergraph.edges():
        #     # PRIMAL GRAPH CONSTRUCTION
        #     for i, j in combinations(self.hypergraph.get_edge(e), 2):
        #         if i < j:
        #             self.add_clause([-self.ord[i][j], self.arc[i][j]])
        #             self.add_clause([self.ord[i][j], self.arc[j][i]])
        for e in self.hypergraph.edges():
            # PRIMAL GRAPH CONSTRUCTION
            for i, j in combinations(self.hypergraph.get_edge(e), 2):
                if i > j:
                    i, j = j, i
                if i < j:
                    # AS CLAUSE
                    self.add_clause([self.ord[i][j], self.arc[j][i]])
                    self.add_clause([-self.ord[i][j], self.arc[i][j]])

        logging.info('Edges Elimintation')
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                if i == j:
                    continue
                for l in range(j + 1, n + 1):
                    if i == l:
                        continue

                    # AS CLAUSE
                    self.add_clause([-self.arc[i][j], -self.arc[i][l], -self.ord[j][l], self.arc[j][l]])
                    self.add_clause([-self.arc[i][j], -self.arc[i][l], self.ord[j][l], self.arc[l][j]])
                    # redundant
                    self.add_clause([-self.arc[i][j], -self.arc[i][l], self.arc[j][l], self.arc[l][j]])

        logging.info('Forbid Self Loops')
        # forbid self loops
        for i in range(1, n + 1):
            # self.__solver.add_assertion(Not(self.literal(self.arc[i][i])))
            # self.stream.write("(assert (not arc_{i}_{i}))\n".format(i=i))
            self.add_clause([-self.arc[i][i]])

    def cover(self, n):
        # If a vertex j is in the bag, it must be covered:
        # assert (=> arc_ij  (>= (+ weight_j_e2 weight_j_e5 weight_j_e7 ) 1) )
        # TODO: double-check the iterator over i
        logging.info('Vertex in bag -> covered')
        logging.debug("Edges %s" % self.hypergraph.edges())
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                if i == j:
                    continue

                logging.debug(f"i={i}, j={j}")
                logging.debug(f"edges: {self.hypergraph.edges()}")

                # arc_ij then j must be covered by some edge (because j will end up in one bag)
                weights = []
                C = []
                for e in self.hypergraph.incident_edges(j):
                    logging.debug(" i=%s, j=%s, e=%s" % (i, j, e))
                    C.append(self.weight[i][e])
                    weights.append(f"weight_{i}_e{e}")

                if len(weights) > 1:
                    self.stream.write(
                        "(assert (=> arc_{i}_{j} (>= (+ {weights}) 1)))\n".format(i=i, j=j, weights=" ".join(weights)))
                elif len(weights) == 1:
                    self.stream.write(
                        "(assert (=> arc_{i}_{j} (>= {weights} 1)))\n".format(i=i, j=j, weights=weights[0]))

                # arc_ij then i most be covered by some edge (because i will end up in one bag)
                weights = []
                C = []
                for e in self.hypergraph.incident_edges(i):
                    logging.debug(" i=%s, j=%s, e=%s" % (i, j, e))
                    C.append(self.weight[i][e])
                    weights.append(f"weight_{i}_e{e}")

                if len(weights) > 1:
                    self.stream.write(
                        "(assert (>= (+ {weights}) 1))\n".format(weights=" ".join(weights)))
                elif len(weights) == 1:
                    self.stream.write(f"(assert (>= {weights[0]} 1))\n")
        # assert (=> arc_ij  (>= (+ weight_j_e2 weight_j_e5 weight_j_e7 ) 1) )

    def break_dynamic_clique(self): #, clique):
        self.add_clause([self.bb(i) for i in self.hypergraph.nodes()])
        for i in self.hypergraph.nodes():
            # COMPUTATION of out-degree od
            self.stream.write(f"(assert (= {self.od[i]} (+ {self.literal_list([self.arc[i][j] for j in self.hypergraph.nodes() if i != j])})))\n")
            for j in self.hypergraph.nodes():
                if i < j:
                    # only one biggest bag bb
                    self.add_clause([-self.bb[i], -self.bb[j]])
                # biggest bag needs to reach all vertices afterwards
                self.add_clause([-self.ord[i][j], self.arc[i][j], -self.bb[i]])
                # biggest bag indeed the biggest
                self.stream.write(f"(assert (or {self.literal_list([-self.ord[i][j], self.bb[i], -self.bb[j]])} (<= {self.od[i], self.od[j]})))\n")

                if i < j: # ACTUAL CLIQUE BREAKING as below
                    sign = 1 if (self.top_ord is not None and self.top_ord_rev[i] < self.top_ord_rev[j]) or (self.top_ord is None) else -1
                    self.add_clause([-self.l[i], -self.l[j], sign * self.ord[i][j]]) # vertices of the clique are ordered lexikog
                    self.add_clause([self.l[i], -self.l[j], self.ord[i][j]]) # vertices not in the clique are ordered before the clique

                # COMPUTATION OF ELEMENTS IN THE CLIQUE -> use l for that
                # l is ONLY for clique members
                self.add_clause([-self.l[i], self.bb[i], -self.bb[j], self.ord[j][i]])
                # member of the clique are for sure in l
                self.add_clause([-self.bb[i], -self.ord[i][j], self.l[j]])
            # bb is always in the clique -> l
            self.add_clause([-self.bb[i], self.l[i]])

            # FIX last of top_ord, contained in ACTUAL CLIQUE BREAKING as below
            if self.top_ord is not None:
                self.stream.write(
                    f"(assert (or (= {self.od[i]} 0) {self.literal_list([-self.last[i]])}))\n")
                #self.stream.write(
                #    f"(assert (or (> {self.od[i]} 0) {self.literal_list([-self.l[i], self.last[i]])}))\n")

        #TODO: break symmetry as below

    def break_clique(self, clique):
        if clique:
            if len(clique) == 0: #dynamic clique symm breaking
                self.break_dynamic_clique()
            else:
                # set max u of top_ord within clique to last(u)
                if self.top_ord is not None:
                    m = max([self.top_ord_rev[j] for j in clique])
                    self.add_clause([-self.last[self.top_ord[m]]])

                # Vertices not in the clique are ordered before the clique
                for i in self.hypergraph.nodes():
                    if i in clique:
                        continue
                    for j in clique:
                        self.add_clause([self.ord[i][j]])
                        # if i < j:
                        #    self.add_clause([self.ord[i][j]])
                        #else:
                        #    self.add_clause([-self.ord[j][i]])

                # Vertices of the clique are ordered lexicographically
                for i in clique:
                    for j in clique:
                        if i < j:
                            if (self.top_ord is not None and self.top_ord_rev[i] < self.top_ord_rev[j]) or \
                                    (self.top_ord is None):
                                self.add_clause([self.ord[i][j]])
                            else:
                                self.add_clause([-self.ord[i][j]])

    # twins is a list of list of vertices that are twins
    def encode_twins(self, twin_iter, clique, topsort):
        logging.info("Hypergraph %s" % self.hypergraph.number_of_nodes())
        if not clique:
            clique = []
        if twin_iter:
            # vertices of a twin class are order lexicographically
            for twins in twin_iter:
                logging.info("Twins are %s" % twins)
                if len(twins) <= 1:
                    continue
                for i in twins:
                    if i in clique:
                        continue
                    for j in twins:
                        if i != j:
                            if j in clique:
                                continue
                            logging.info("i={i}, j={j}".format(i=i, j=j))
                            logging.info("ord=%s,%s" % (len(self.ord), len(self.ord[0])))
                            if (topsort == 0 and i < j) or (topsort and self.top_ord_rev[i] < self.top_ord_rev[j]):
                                self.add_clause([self.ord[i][j]])
                                # self.stream.write("(assert (ord_{i}_{j}))\n".format(i=i, j=j))
                            # else:
                            #     self.add_clause([-self.ord[j][i]])
                            #     self.stream.write("(assert (-ord_{j}{i}))\n".format(i=i, j=j))

    def encode(self, clique=None, topsort=0, twins=None):
        n = self.hypergraph.number_of_nodes()

        self.elimination_ordering(n)
        self.cover(n)
        self.break_clique(clique=clique)
        self.encode_twins(twin_iter=twins, clique=clique, topsort=topsort)
        if topsort > 0:
            self.topsort(topsort=topsort)

    def topsort(self, topsort=1):
        assert(topsort >= 1)
        n = self.hypergraph.number_of_nodes()
        #m = self.hypergraph.number_of_edges()
        # only one last(i) allowed
        for i in range(1,n+1):
            for j in range(i+1,n+1):
                self.add_clause([-self.last[i], -self.last[j]])

        # ensure non-last vertices get a smallest vertex
        for i in range(1,n+1):
            C = [self.last[i]]
            for j in range(1,n+1) if topsort == 1 else self.hypergraph.adjByNode(i):
                if i != j:
                    C.append(self.smallest[i][j])
            self.add_clause(C)

        if topsort == 1:
            # if j smallest of i, we require an arc from i to j
            for i in range(1,n+1):
                for j in range(1,n+1):
                    if i != j:
                        self.add_clause([-self.smallest[i][j], self.arc[i][j]])

            # we only want the left-most vertex w
            for i in range(1,n+1):
                for j in range(1,n+1):
                    for w in range(1, n + 1):
                        if i != j and i != w and w != j: # self.top_ord_rev[w] < self.top_ord_rev[j]:
                            self.add_clause([-self.arc[i][w], -self.arc[i][j], -self.ord[w][j], -self.smallest[i][j]])
        else:
            # if j smallest of i -> no last possible for i and vice versa
            # for i in range(1,n+1):
            #    for j in range(1,n+1):
            #        if i != j:
            #            self.add_clause([-self.last[i], -self.smallest[i][j]])

            # we only want the left-most vertex w
            for i in range(1,n+1):
                for j in self.hypergraph.adjByNode(i):
                    for w in self.hypergraph.adjByNode(i):
                        assert(i != j and i != w)
                        if j != w:
                            self.add_clause([-self.ord[w][j], -self.smallest[i][j]])

        for i in range(1,n+1):
            for j in range(1,n+1):
                for w in range(1,n+1):
                    if self.top_ord_rev[i] < self.top_ord_rev[j] and i != w and j != w:
                        self.add_clause([self.ord[j][i], -self.smallest[i][w], self.ord[w][j]])


    def configration(self):
        # z3.set_option(html_mode=False)
        # z3.set_option(rational_to_decimal=True)
        # z3.set_option(precision=30)
        # z3.set_option(verbose=1)
        pass

    def _get_ordering(self, model):
        logging.info("Reconstruct Ordering")
        ordering = []
        for i in range(1, self.hypergraph.number_of_nodes() + 1):
            pos = 0
            for j in ordering:
                # We know j is smaller due to range processing
                if not model["ord_{}_{}".format(j, i)]:
                    break
                # Move current element one position forward
                pos += 1
            ordering.insert(pos, i)

        return ordering

    def solve(self, m=None, lbound=1, ubound=None, clique=None, topsort=0, twins=None):
        opt = False
        if not m:
            opt = True
        if not ubound:
            ubound = len(self.hypergraph.edges())
        logging.info("WE ARE SOLVING FOR fraction = %s" % m)

        self.prepare_vars(topsort, clique)
        self.configration()

        enc_wall = time.time()
        self.encode(clique=clique, topsort=topsort, twins=twins)
        enc_wall = time.time() - enc_wall
        logging.warning("Encoding time %s" % enc_wall)

        logging.info("SMT solving for: %s" % m)
        # assert(False)
        self.fractional_counters(m=m)
        # self.add_all_at_most(m)
        ret = {"objective": "nan", "decomposition": None, 'enc_wall': enc_wall,
               "smt_solver_stats": None, "smt_objective": "nan"}

        if opt:
            self.encode_opt(opt, lbound=lbound, ubound=ubound)
            self.stream.write("(check-sat)\n(get-value (m))\n(get-objectives)\n(get-model)\n")
            # self.stream.write("(check-sat)\n(get-model)\n")
            if self._debug:
                with open('tmp_out_2.txt', 'w') as f:
                    f.write(self.stream.getvalue())

            # TODO: delete configurable
            # TODO: prefix='tmp'[, dir=None
            # TODO: move to shm
            with tempfile.SpooledTemporaryFile() as modelf:
                with tempfile.SpooledTemporaryFile() as errorf:
                    output, is_z3 = self.run_solver(self.stream, modelf, errorf, lbound, self._odebug)
                    res = self.decode(output, is_z3=is_z3, lbound=lbound)
                    ret.update(res)
            return ret

        else:
            raise NotImplementedError

    def encode_opt(self, opt, lbound=None, ubound=None):
        if opt:
            self.stream.write("(assert (>= m 1))\n")
            self.stream.write("(minimize m)\n")
            if ubound:
                self.stream.write(f"(assert (<= m {ubound}))\n")
            if lbound:
                self.stream.write(f"(assert (>= m {lbound}))\n")

    def decode(self, output, is_z3, lbound, htd=False, repair=True):
        ret = {"objective": "nan", "decomposition": None, "arcs": None, "ord": None, "weights": None}

        model = {}
        regex_real = re.compile("\(\/\s+(?P<num>([0-9]+(\.[0-9]+)?))\s+(?P<den>([0-9]+(\.[0-9]+)?))\)")

        if is_z3:
            for line in output.split('\n'):
                if 'success' in line:
                    continue
                # print(line)
            lines = re.findall(
                '\(define\-fun ([^ ]*) \(\) [a-zA-Z]*\s*(([a-zA-Z0-9]*(\.[0-9]+)?)|(\(\/\s+[0-9]+(\.[0-9]+)?\s+[0-9]+(\.[0-9]+)?\)))\)',
                output)

            for var, val, _, _, _, _, _ in lines:
                if val == "true":
                    model[var] = True
                elif val == "false":
                    model[var] = False
                elif val.startswith("(/"):
                    g = regex_real.match(val)
                    num, den = float(g.group("num")), float(g.group("den"))
                    if not num.is_integer() or not den.is_integer():
                        logging.error(f"Received a non-rational number as output. Value was: {val} num: {num} "
                                      f"({num.is_integer()}) den: {den} ({den.is_integer()})")
                        raise RuntimeError
                    model[var] = Fraction(numerator=int(num), denominator=int(den))
                else:
                    model[var] = Fraction(val)
        else:
            regex = re.compile(
                '\s*\((?P<var>([a-zA-Z]+(|\_[0-9]+\_[a-zA-Z]*[0-9]+)))\s*(?P<val>(true|false|\(\/\s+[0-9]+ [0-9]+\s*\)|[0-9]+))\)\s*')

            for line in output.split("\n"):
                if 'success' in line:
                    continue
                if line.startswith("( "):
                    line = line[1:]
                if line.endswith(" )"):
                    line = line[:-1]
                m = regex.match(line)
                if m:
                    var, val = m.group("var"), m.group("val")
                    logging.debug(f"var: {var} / val: {val}")
                    if val == "true":
                        model[var] = True
                    elif val == "false":
                        model[var] = False
                    elif val.startswith("(/"):
                        g = regex_real.match(val)
                        num, den = g.group("num"), g.group("den")
                        logging.debug(f"var/val: {var}={val} | num: {num} den: {den}")
                        model[var] = Fraction(numerator=int(g.group("num")), denominator=int(g.group("den")))
                    else:
                        model[var] = Fraction(val)

        # try:
        ordering = self._get_ordering(model)
        weights = self._get_weights(model, ordering)
        arcs = self._get_arcs(model)

        fhtd = FractionalHypertreeDecomposition.from_ordering(hypergraph=self.hypergraph, ordering=ordering,
                                                              weights=weights,
                                                              checker_epsilon=self.__checker_epsilon)
        rsx = model["m"]

        if lbound == 1 and not rsx - self.__checker_epsilon <= fhtd.width() <= rsx + self.__checker_epsilon:
            raise ValueError("fhtw should be {0}, but actually is {1}".format(rsx, fhtd.width()))
        elif lbound > 1 and rsx + self.__checker_epsilon < fhtd.width():
            raise ValueError("fhtw should be at most {0}, but actually is {1}".format(rsx, fhtd.width()))
        # TODO: solver call statistics
        # stats = str(self.__solver.statistics())
        # regex = re.compile(r"\s*:(?P<group>[A-Za-z\-]+)\s+(?P<val>[0-9]+(\.[0-9]+)*)\s*$")
        # res_stats = {}
        # for line in stats.split("\n"):
        #     if line[0] == "(":
        #         line = line[1:]
        #     m = regex.match(line)
        #     if m:
        #         res_stats[m.group("group")] = m.group("val")

        # TODO: handle unsat
        ret.update({"objective": fhtd.width(), "decomposition": fhtd,  # "smt_solver_stats": res_stats,
                    })
        return ret
        #
        # return DecompositionResult(htdd.width(), htdd, arcs, ordering, weights)

    def _get_weights(self, model, ordering):
        ret = {}
        n = self.hypergraph.number_of_nodes()

        for i in range(1, n + 1):
            # print 'bag %i'
            ret[i] = {}
            for e in self.hypergraph.edges():
                assert (e > 0)
                ret[i][e] = model["weight_{}_e{}".format(i, e)]
                val = model[self.literal(self.weight[i][e])]
                logging.debug(" Mod weight_{i}_e{j}={val}".format(i=i, j=e, val=val))
                if self.ghtd:
                    ret[i][e] = val.as_long()
                else:
                    if isinstance(val, dict):
                        ret[i][e] = val['numerator'] / val['denominator']
                    else:
                        ret[i][e] = val
                    # ret[i][e] = float(val['numerator']) / float(val['denominator'])

        last_vertex = ordering[-1]
        incident_edges = self.hypergraph.incident_edges(last_vertex).keys()
        if len(incident_edges) == 0:
            raise TypeError("Fractional Hypertree Decompositions for graphs with isolated vertices.")

        return ret

    # def _get_weights(self, model, ordering):
    #     logging.info("Reconstruct weights")
    #     ret = {}
    #     n = self.hypergraph.number_of_nodes()
    #     logging.debug(" Model = %s" % model)
    #     for i in range(1, n + 1):
    #         # print 'bag %i'
    #         ret[i] = {}
    #         for e in self.hypergraph.edges():
    #             assert (e > 0)
    #             val = model[self.literal(self.weight[i][e])]
    #             logging.debug(" Mod weight_{i}_e{j}={val}".format(i=i, j=e, val=val))
    #             if self.ghtd:
    #                 ret[i][e] = val.as_long()
    #             else:
    #                 ret[i][e] = float(val.numerator_as_long()) / float(val.denominator_as_long())
    #
    #     last_vertex = ordering[-1]
    #     incident_edges = self.hypergraph.incident_edges(last_vertex).keys()
    #     if len(incident_edges) == 0:
    #         raise TypeError("Fractional Hypertree Decompositions for graphs with isolated vertices.")
    #
    #     logging.debug("Weights = %s" % ret)
    #     return ret

    def _get_arcs(self, model):
        n = self.hypergraph.number_of_nodes()
        ret = {}

        for i in range(1, n + 1):
            ret[i] = {}
            # ret[i][i] = True
            for j in range(1, n + 1):
                if i != j:
                    ret[i][j] = model["arc_{}_{}".format(i, j)]

        return ret

    def run_solver(self, inp_stream, modelf, errorf, lbound, odebug=None):
        if self._debug:
            with open('myfile.txt', 'w') as myf:
                myf.write(inp_stream.getvalue())

        solver_name = subprocess.check_output([self.solver_bin, "-version"]).decode()
        logging.info(f"Solver Name: {solver_name}")
        solver_name = solver_name.split(' ')[0]
        # p_solver = Popen(run_cmd, stdout=PIPE, stderr=PIPE, shell=True, close_fds=True, cwd=outdir)
        # inpf.seek(0)
        if 'z3' in solver_name.lower():
            p1 = subprocess.Popen([self.solver_bin, '-st', '-smt2', '-in'], stdin=subprocess.PIPE, stdout=modelf,
                                  stderr=errorf)
            is_z3 = True
        elif 'MathSAT5' in solver_name:
            p1 = subprocess.Popen(
                [self.solver_bin, '-stats', "-verbosity=2", "-input=smt2", "-opt.theory.la.delta_pow=18"], #"-opt.theory.la.delta_pow=9"],
                stdin=subprocess.PIPE, stdout=modelf, stderr=errorf, shell=True)
            is_z3 = False
        else:
            logging.error(f"Unknown solver {solver_name}")
            raise RuntimeError

        p1.communicate(input=inp_stream.getvalue().encode())
        if p1.returncode != 0:
            logging.error("Solver-Process terminated with returncode {}".format(p1.returncode))
            raise RuntimeError
        errorf.seek(0)
        err = errorf.read().decode('utf8')
        if err != '':
            logging.error(err)
        #     exit(1)
        modelf.seek(0)
        output = modelf.read().decode('utf8')

        stored_file = False
        for line in output.split('\n'):
            if 'success' in line:
                continue
            if 'error' in line:
                with tempfile.NamedTemporaryFile(dir=odebug, prefix='smt_', delete=False) as inpf:
                    inpf.write(inp_stream.getvalue().encode())
                    logging.error(f"Solver reported an error. Encoding stored in {inpf.name}")
                stored_file = True
            # print(line)
        # TODO: statistics
        return output, is_z3
