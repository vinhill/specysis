

class LLMTask:
    def __init__(self, context, max_steps: int = 10):
        """
        context: bs4 element
        """
        self.prev, self.cur, self.next = context, context, context
        self.done = False
        self.solution = []
        self.max_steps = max_steps

    def query_llm(self, msg: str) -> str:
        return input(msg)
    
    def fmt_node(self, node) -> str:
        return str(node).replace("\n", "")
    
    def make_initial_prompt(self, task) -> str:
        methods = ", ".join([
            "get_previous_context()",
            "get_next_context()",
            "add_dependencies(concept, [dependencies])",
            "create_concept(concept)",
            "finish()",
        ])
        
        context = self.fmt_node(self.cur)

        template = """
        Here is the spec context:
        {context}
        Here are the available methods:
        {methods}
        Here is your task:
        {task}
        Provide the next method call: 
        """

        template = re.sub(r"\ +", " ", template)
        return template.format(context=context, methods=methods, task=task)

    def prompt(self, msg: str) -> Tuple[str, List[str]]:
        msg = self.make_initial_prompt(msg)

        for _ in range(self.max_steps):
            rsp = self.query_llm(msg)
            method, args = self.parse_response(rsp)
            try:
                msg = getattr(self, method)(*args)
            except Exception as e:
                logging.warning("LLM failed to resolve task. Called %s(%s). Error: %s", method, args, e)
                msg = "Unknown method call."
            if self.done:
                return self.solution
        logging.debug("LLM failed to resolve task %s", msg)
        return None

    def parse_response(self, msg: str):
        # response is one method to call on self
        match = re.match(r"(?P<method>[a-zA-Z0-9_]+)\((?P<args>[^\)]*)\)", msg)
        if not match:
            return None
        
        method = match.group("method")
        args = match.group("args")
        if args != "":
            args = args.split(",")
        else:
            args = []

        # parse list args
        for i, arg in enumerate(args):
            match = re.match(r"^\[(?P<list>[^\]]*)\]$", arg)
            if match:
                args[i] = match.group("list").split(",")

        return method, args
    
    def add_dependencies(self, concept: str, dependencies: List[str]):
        self.solution.append(("add", concept, dependencies))
        return "done"

    def create_concept(self, concept: str):
        self.solution.append(("new", concept))
        return "done"

    def finish(self):
        self.done = True

    def get_previous_context(self) -> str:
        if not self.prev:
            return "<start of file>"
        self.prev = self.prev.find_previous_sibling()
        if not self.prev:
            return "<start of file>"
        return self.fmt_node(self.prev)

    def get_next_context(self):
        if not self.next:
            return "<end of file>"
        self.next = self.next.find_next_sibling()
        if not self.next:
            return "<end of file>"
        return self.fmt_node(self.next)


class LLM:
    def __init__(self):
        pass

    def resolve_multiple_dfns(self, parent, dfn):
        task = LLMTask(parent)
        identifier = extract_identifier(dfn)
        task.prompt(f"Multiple dfns in context, resolve '{identifier}'. ")

    def resolve_unused_content(self, content):
        pass

    def resolve_unknown_dfn(self, dfn):
        pass
