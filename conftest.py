import ast
import json

import parso
import pytest

from collections import OrderedDict
from types import GeneratorType as generator
from itertools import chain
from pathlib import Path

from objectpath import Tree
from mongoquery import Query

from tests.nodes import convert_node, flatten
from tests.template import Template


class Parser:
    def __init__(self, file_name, nodes):

        sensor = Path.cwd() / "sensor"
        # ext = sensor / "extensions"

        self.data = {
            "success": True,
            "full_path": "",
            "message": "",
            "start_pos": 0,
            "nodes": nodes,
        }

        if file_name is not None:
            path = lambda root, fn: root / f"{fn}.py"
            if file_name == "sensor":
                full_path = path(Path.cwd(), file_name)
            else:
                full_path = path(sensor, file_name)

            grammar = parso.load_grammar()
            module = grammar.parse(path=full_path)
            self.data["success"] = len(grammar.iter_errors(module)) == 0

        if self.data["success"]:
            self.data["message"] = "Syntax: valid"
            if file_name is not None:
                self.data["nodes"] = convert_node(ast.parse(full_path.read_text()))
                self.data["code"] = full_path.read_text()

        else:
            self.data["message"] = grammar.iter_errors(module)[0].message
            self.data["start_pos"] = grammar.iter_errors(module)[0].start_pos[0]

    @property
    def nodes(self):
        return self.data["nodes"]

    n = nodes

    @property
    def success(self):
        return self.data["success"]

    @property
    def code(self):
        return self.data["code"]

    def query(self, pattern):
        nodes = Template(pattern).process(self.code)
        if isinstance(nodes, list) and len(nodes) == 1:
            nodes = nodes[0]

        return Parser(None, nodes)

    def query_raw(self, pattern):
        nodes = Template(pattern).process(self.code, True)
        if isinstance(nodes, list) and len(nodes) == 1:
            nodes = [flatten(convert_node(node)) for node in nodes[0].body]
        return Parser(None, nodes)

    def last_line(self):
        return flatten(self.nodes["body"][-1])

    @property
    def message(self):
        return f'{self.data["message"]} on or around line {self.data["start_pos"]} in `{self.data["full_path"]}`.'

    def match(self, template):
        return Parser(None, list(filter(Query(template).match, self.nodes)))

    def execute(self, expr):
        result = Tree(self.nodes).execute(expr)
        if not isinstance(result, (generator, chain, map)):
            return Parser(None, result)
        process = list(result)
        return (
            Parser(None, process[0]) if len(process) == 1 else Parser(None, process)
        )

    ex = execute

    def exists(self):
        return bool(self.nodes)

    def calls(self):
        nodes = self.execute("$.body[@.type is 'Expr' and @.value.type is 'Call']").n
        node_list = [nodes] if isinstance(nodes, dict) else nodes

        return Parser(None, [flatten(node) for node in node_list])

    def assign_(self):
        return Parser(None, [flatten(self.execute("$.body[@.type is 'Assign']").n)])
    
    def def_args_(self, name):
        return Parser(
            None,
            [
                flatten(
                    self.execute(
                        f"$.body[@.type is 'FunctionDef' and @.name is '{name}']"
                    ).n
                )
            ],
        )

    def assigns(self):
        return Parser(
            None,
            [flatten(node) for node in self.execute("$.body[@.type is 'Assign']").n],
        )

    def globals(self, name):
        return name in self.execute("$.body[@.type is 'Global'].names").n

    def defines(self, name):
        return self.execute(
            f"$.body[@.type is 'FunctionDef' and @.name is '{name}'].(name, args, body, decorator_list)"
        )

    def class_(self, name):
        return self.execute(
            f"$.body[@.type is 'ClassDef' and @.name is '{name}'].(name, args, body)"
        )

    def decorators(self):
        return Parser(None, [flatten(self.execute("$.decorator_list").n)])

    def returns(self, name):
        return name == self.execute("$.body[@.type is 'Return'].value.id").n

    def returns_call(self):
        return Parser(None, [flatten(self.execute("$.body[@.type is 'Return']").n)])

    def method(self, name):
        return self.execute(f"$..body[@.type is 'FunctionDef' and @.name is '{name}']")

    def has_arg(self, name, pos=0):
        nodes = self.execute("$.args.args.arg").n
        return nodes[pos] if isinstance(nodes, list) else nodes

    def imports(self, name):
        return name in self.execute("$.body[@.type is 'Import'].names..name").n

    def for_(self):
        for_body = self.execute("$.body[@.type is 'For'].body").n
        iterators = self.execute("$.body[@.type is 'For'].(target, iter)").n
        return Parser(None, [flatten(for_body), flatten(iterators)])

    def from_imports(self, mod, alias):
        nodes = self.execute(
            f"$.body[@.type is 'ImportFrom' and @.module is '{mod}'].names..name"
        ).n
        return alias in (nodes if isinstance(nodes, list) else [nodes])


@pytest.fixture
def parse():
    def _parse(file_name):
        return Parser(file_name, {})

    return _parse