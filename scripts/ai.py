"""
This command sends information on the current debugging context to OpenAI's GPT-3 large language model
and asks it a question supplied by the user. It then displays GPT-3's response to that question to the
user. Describe thoroughly what your command does. In addition, complete the documentation
in /docs/ and adding the reference in /mkdocs.yml
"""

__AUTHOR__ = "Olivia Lucca Fraser"
__VERSION__ = 0.1
__LICENSE__ = "MIT"

from typing import TYPE_CHECKING, List
import openai
import os
import textwrap
import json
import argparse
import gdb

if TYPE_CHECKING:
    from . import *  # this will allow linting for GEF and GDB


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

LAST_QUESTION = []
LAST_ANSWER = []
LAST_PC = None
LAST_COMMAND = None
HISTORY_LENGTH = 3


def disable_color(t):
    #gdb.execute(f"set style enabled {'off' if t else 'on'}")
    gef.config["gef.disable_color"] = t
    return

def build_prompt(question, command):
    if command is not None:
        return build_prompt_from_command(question, command)

    ## First, get the current GDB context
    ## Let's begin with the assembly near the current instruction
    color_on = gef.config["gef.disable_color"]
    #asm = gdb.execute("context code", to_string=True)
    try:
        asm = gdb.execute("capstone-disassemble --length 32 $pc", to_string=True)
    except:
        asm = gdb.execute("x/16i $pc", to_string=True)
    ## Next, let's get the registers
    #regs = gdb.execute("context regs", to_string=True)
    regs = gdb.execute("info registers", to_string=True)
    ## Finally, let's get the stack
    #stack = gdb.execute("context stack", to_string=True)
    stack = gdb.execute("x/16x $sp", to_string=True)
    ## and the backtrace 
    #trace = gdb.execute("context trace", to_string=True)
    trace = gdb.execute("bt", to_string=True)
    ## the function arguments, if available
    #args = gdb.execute("context args", to_string=True)
    args = gdb.execute("info args", to_string=True)
    ## and the local variables, if available
    local_vars = None #gdb.execute("info locals", to_string=True)
    ## and source information, if available
    source = gdb.execute("list *$pc", to_string=True)

    ## Now, let's build the prompt
    prompt = "Consider the following context in the GDB debugger:\n"

    if True or asm:
        prompt += f"""Here is the assembly near the current instruction:

```
{asm}
```

"""
    if True or regs:
        prompt += f"""Here are the registers:

```
{regs}
```

"""
    if True or stack:
        prompt += f"""Here is the stack:

```
{stack}
```

"""
    if True or trace:
        prompt += f"""Here is the backtrace:

```
{trace}
```
"""
    if args and "No symbol table info available" not in args:
        prompt += f"""Here are the function arguments:

```
{args}
```
"""

    if local_vars and "No symbol table info available" not in local_vars:
        prompt += f"""Here are the local variables:

```
{local_vars}
```
"""

    if source:
        prompt += f"""Here is the source code near the current instruction:

```
{source}
```
"""
    return finish_prompt(prompt, question)


def build_prompt_from_command(question, command):
    prompt = f"""Running the command `command` in the GDB debugger yields the following output:\n"""
    output = gdb.execute(command, to_string=True)
    gef_print(output)
    prompt += f"""\n```\n{output}\n```\n"""
    return finish_prompt(prompt, question)


def strip_colors(text):
    ## Now remove all ANSI color codes from the prompt
    text = re.sub(r"\x1b[^m]*m", "", text)
    return text


def finish_prompt(prompt, question):
    for (q,a) in zip(LAST_QUESTION, LAST_ANSWER):
        prompt += f"""Question: {q}\n\nAnswer: {a}\n\n"""
    prompt += f"""Question: {question}\n\nAnswer: """
    prompt = strip_colors(prompt)
    return prompt


def query_openai(prompt, engine="text-davinci-003", max_tokens=100, temperature=0.0):
    response = openai.Completion.create(
        engine=engine,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        stop = ["Question:"],
    )
    return response.choices[0].text


@register
class AI(GenericCommand):
    """Query GPT-3 for insights into the debugging context."""
    _cmdline_ = "ai"
    _syntax_ = "{:s} <QUESTION>".format(_cmdline_)
    _example_ = """
gef➤  ai what will the next two instructions do the the eax and ecx registers?
 The next two instructions will move the values stored in the esi and edi registers into the eax and ecx registers, respectively.
gef➤  ai say that again but as a limerick

The eax and ecx registers will fill
With the values stored in esi and edi still
The instructions will move 
Their values to improve
And the registers will have a new thrill

gef➤  ai what was the name of the function most recently called?
 strcmp
gef➤  ai how do you know this?
 The assembly code shows that the function call 0x7ffff7fea240 <strcmp> was made just before the current instruction at 0x7ffff7fce2a7 <check_match+103>.
"""

    def pre_load(self) -> None:
        super().pre_load()

    def __init__(self) -> None:
        super().__init__(complete=gdb.COMPLETE_NONE)

    def post_load(self) -> None:
        super().post_load()

    @only_if_gdb_running
    def do_invoke(self, argv: List[str]):
        global LAST_QUESTION, LAST_ANSWER, LAST_PC, LAST_COMMAND
        if not OPENAI_API_KEY:
            gef_print("Please set the OPENAI_API_KEY environment variable.")
            return
        parser = argparse.ArgumentParser(prog=self._cmdline_)
        parser.add_argument("question", type=str, default=None, nargs="+", help="The question to ask.")
        parser.add_argument("-e", "--engine", default="text-davinci-003", help="The OpenAI engine to use.")
        parser.add_argument("-t", "--temperature", default=0.5, type=float, help="The temperature to use.")
        parser.add_argument("-m", "--max-tokens", default=100, type=int, help="The maximum number of tokens to generate.")
        parser.add_argument("-v", "--verbose", action="store_true", help="Print the prompt and response.")
        parser.add_argument("-c", "--command", type=str, default=None, help="Run a command in the GDB debugger and ask a question about the output.")
        args = parser.parse_args(argv)
       
        if not args.question:
            parser.print_help()
            return
        
        question = " ".join(args.question)
        command = args.command
        current_pc = gdb.execute("info reg $pc", to_string=True)
        if current_pc == LAST_PC and command is None:
            command = LAST_COMMAND
        else:
            LAST_COMMAND = command
        if LAST_PC != current_pc or LAST_COMMAND != command:
            LAST_QUESTION.clear()
            LAST_ANSWER.clear()

        prompt = build_prompt(question, command)
        if args.verbose:
            gef_print(f"Sending this prompt to OpenAI:\n\n{prompt}")
        res = query_openai(prompt, engine=args.engine, max_tokens=args.max_tokens, temperature=args.temperature).strip()
        LAST_QUESTION.append(question)
        LAST_ANSWER.append(res)
        LAST_PC = current_pc
        if len(LAST_QUESTION) > HISTORY_LENGTH:
            LAST_QUESTION.pop(0)
            LAST_ANSWER.pop(0)
        term_width = os.get_terminal_size().columns
        answer = textwrap.fill(res, term_width)
        gef_print(answer)
        return
