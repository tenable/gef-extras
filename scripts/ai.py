"""
Describe thoroughly what your command does. In addition, complete the documentation
in /docs/ and adding the reference in /mkdocs.yml
"""

__AUTHOR__ = "Olivia Lucca Fraser"
__VERSION__ = 0.1
__LICENSE__ = "MIT"

from typing import TYPE_CHECKING, List
import openai
import os
import json
import argparse
import gdb

if TYPE_CHECKING:
    from . import *  # this will allow linting for GEF and GDB


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def build_prompt(question):
    ## First, get the current GDB context
    ## Let's begin with the assembly near the current instruction
    asm = gdb.execute("context code", to_string=True)
    ## Next, let's get the registers
    regs = gdb.execute("context regs", to_string=True)
    ## Finally, let's get the stack
    stack = gdb.execute("context stack", to_string=True)
    ## Now, let's build the prompt
    prompt = f"""\
Consider the following context in the GDB debugger:

Here is the assembly near the current instruction:

```
{asm}
```

Here is the current state of the registers:

```
{regs}
```

Here is the current state of the stack:

```
{stack}
```

Question: {question}

Answer: """
    return prompt


def query_openai(prompt, engine="text-davinci-003", max_tokens=100, temperature=0.0):
    response = openai.Completion.create(
        engine=engine,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].text


@register
class AI(GenericCommand):
    """Query GPT-3 for insights into the debugging context."""
    _cmdline_ = "ai"
    _syntax_ = "{:s} <QUESTION>".format(_cmdline_)

    def pre_load(self) -> None:
        super().pre_load()

    def __init__(self) -> None:
        super().__init__(complete=gdb.COMPLETE_NONE)

    def post_load(self) -> None:
        super().post_load()

    @only_if_gdb_running
    def do_invoke(self, argv: List[str]):
        if not OPENAI_API_KEY:
            gef_print("Please set the OPENAI_API_KEY environment variable.")
            return
        parser = argparse.ArgumentParser(prog=self._cmdline_)
        parser.add_argument("question", nargs="+", help="The question to ask.")
        parser.add_argument("-e", "--engine", default="text-davinci-003", help="The OpenAI engine to use.")
        parser.add_argument("-t", "--temperature", default=0.5, type=float, help="The temperature to use.")
        parser.add_argument("-m", "--max-tokens", default=100, type=int, help="The maximum number of tokens to generate.")
        args = parser.parse_args(argv)
        question = " ".join(args.question)
        prompt = build_prompt(question)
        res = query_openai(prompt, engine=args.engine, max_tokens=args.max_tokens, temperature=args.temperature)
        gef_print(res)
        return
